"""The agent loop: ask the model, run tools, repeat, streaming SSE."""

import asyncio
import json
import time
from typing import AsyncGenerator

import httpx

from wsh.agent.client import call_model
from wsh.config import MAX_STEPS, MODEL, MODEL_MAX_RETRIES
from wsh.models import (
    AnswerEvent,
    ErrorEvent,
    SessionEvent,
    SseEvent,
    StatusEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from wsh.session import SessionLog
from wsh.tools import TOOL_REGISTRY, call_tool

RETRY_BACKOFF_S = 1.0  # seconds between retry attempts (exponential/jitter out of scope)


def _retryable(exc: BaseException) -> bool:
    """True for transient failures worth retrying: 503 and transport errors."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 503
    if isinstance(exc, (httpx.DecodingError, httpx.TooManyRedirects)):
        return False
    return isinstance(exc, httpx.RequestError)


def _error_message(exc: BaseException) -> str:
    """A model-call error message that names the exception type and is never empty."""
    name = type(exc).__name__
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Model error ({name}): {exc.response.status_code} {exc.response.text}"
    detail = str(exc)
    return f"Could not reach the model ({name}): {detail or 'no detail'}"


async def agent_loop(messages: list[dict], log: SessionLog) -> AsyncGenerator[SseEvent, None]:
    """
    The whole point of a harness. Yields typed SseEvent models for the browser.

    Steps:
      1. ask the model
      2. no tool calls? -> stream the answer and stop
      3. tool calls? -> look each one up in TOOL_REGISTRY, run it,
         stream its result, append a 'tool' message, and go back to step 1

    Every model request/response is also appended to the session's JSONL log,
    write-ahead: the request is recorded *before* it is sent.
    """
    # Work on a copy so the caller's list isn't mutated by surprise.
    convo = [dict(m) for m in messages]

    # Tell the browser which session this is, so it can reuse the id next turn.
    yield SessionEvent(type="session", session_id=log.session_id)

    for _ in range(MAX_STEPS):
        step = log.next_step()
        yield StatusEvent(type="status", text="asking the model…")

        # WAL: write the (delta-only) request BEFORE hitting the model, so a
        # crash mid-flight still leaves a record of what we tried to send.
        log.write_request(convo, step, MODEL)
        started = time.monotonic()

        attempts = 0
        while True:
            try:
                data = await call_model(convo)
                break
            except Exception as e:
                if _retryable(e) and attempts < MODEL_MAX_RETRIES:
                    attempts += 1
                    yield StatusEvent(
                        type="status",
                        text=f"retrying ({attempts}/{MODEL_MAX_RETRIES})…",
                    )
                    await asyncio.sleep(RETRY_BACKOFF_S)
                    continue
                message = _error_message(e)
                log.write_error(message, step)
                yield ErrorEvent(type="error", message=message)
                return

        latency_ms = round((time.monotonic() - started) * 1000)

        choice = data["choices"][0]["message"]
        # Some providers (e.g. DeepSeek reasoner) return `content: null` when the
        # turn is all tool calls; keep it a string so the echoed-back history is
        # accepted by stricter APIs.
        if choice.get("content") is None:
            choice["content"] = ""
        # Keep the assistant's message in the conversation, including tool_calls.
        convo.append(choice)

        finish_reason = data["choices"][0].get("finish_reason")
        usage = data.get("usage")
        log.write_response(choice, step, MODEL, latency_ms, finish_reason, usage)

        tool_calls = choice.get("tool_calls") or []
        if not tool_calls:
            # The model is done. Send the answer plus the NEW full history,
            # so the web UI can send it back next turn. `convo[1:]` drops the
            # system message, which the UI never needs to echo back.
            yield AnswerEvent(
                type="answer",
                session_id=log.session_id,
                content=choice.get("content") or "",
                messages=convo[1:],
            )
            return

        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name")
            func = TOOL_REGISTRY.get(name)

            if func is None:
                yield ToolResultEvent(
                    type="tool_result",
                    name=name,
                    result={"error": f"unknown tool: {name}"},
                )
                continue

            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}

            yield ToolCallEvent(type="tool_call", name=name, args=args)
            result = await call_tool(func, args)
            yield ToolResultEvent(type="tool_result", name=name, result=result)

            # Append a proper "tool" message so the model sees the output.
            convo.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": name,
                    "content": json.dumps(result, default=str),
                }
            )

    # The model never produced a tool-call-free answer within MAX_STEPS.
    yield AnswerEvent(
        type="answer",
        session_id=log.session_id,
        content=f"(stopped after {MAX_STEPS} steps)",
        messages=convo[1:],
    )
