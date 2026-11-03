"""The agent loop: ask the model, run tools, repeat, streaming SSE."""

import json
import time

import httpx

from wsh.agent.client import call_model
from wsh.config import MAX_STEPS, MODEL
from wsh.session import SessionLog
from wsh.sse import sse
from wsh.tools import TOOL_REGISTRY, call_tool


async def agent_loop(messages: list[dict], log: SessionLog):
    """
    The whole point of a harness. Yields SSE strings for the browser.

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
    yield sse("session", {"session_id": log.session_id})

    for step in range(1, MAX_STEPS + 1):
        yield sse("status", {"text": "asking the model…"})

        # WAL: write the (delta-only) request BEFORE hitting the model, so a
        # crash mid-flight still leaves a record of what we tried to send.
        log.write_request(convo, step, MODEL)
        started = time.monotonic()

        try:
            data = await call_model(convo)
        except httpx.HTTPStatusError as e:
            message = f"Model error: {e.response.status_code} {e.response.text}"
            log.write_error(message, step)
            yield sse("error", {"message": message})
            return
        except Exception as e:  # network failure, bad key, etc.
            message = f"Could not reach the model: {e}"
            log.write_error(message, step)
            yield sse("error", {"message": message})
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
            yield sse(
                "answer",
                {
                    "session_id": log.session_id,
                    "content": choice.get("content") or "",
                    "messages": convo[1:],
                },
            )
            return

        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name")
            func = TOOL_REGISTRY.get(name)

            if func is None:
                yield sse("tool_result", {"name": name, "result": {"error": f"unknown tool: {name}"}})
                continue

            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}

            yield sse("tool_call", {"name": name, "args": args})
            result = await call_tool(func, args)
            yield sse("tool_result", {"name": name, "result": result})

            # Append a proper "tool" message so the model sees the output.
            convo.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": name,
                    "content": json.dumps(result, default=str),
                }
            )

    yield sse(
        "answer",
        {
            "session_id": log.session_id,
            "content": f"(stopped after {MAX_STEPS} steps)",
            "messages": convo[1:],
        },
    )
