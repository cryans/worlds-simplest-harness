"""The HTTP endpoints: chat (SSE stream), session list/detail, and health."""

import re
import tempfile
import uuid
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from wsh.agent import agent_loop
from wsh.api.app import app
from wsh.config import (
    API_KEY, BASE_URL, MODEL, MAX_STEPS, BASH_TIMEOUT, SAMPLE_PROJECT, LOGS_DIR, make_system_prompt,
)
from wsh.models import ChatRequest, ErrorEvent, SessionList, SessionPayload
from wsh.session import SessionLog, _session_meta, _unanswered_tool_call_indexes, prepare_session
from wsh.sse import sse
from wsh.tools import TOOLS


SMOKE_COMMAND = "@sample-project"
SMOKE_OFF_COMMAND = "@sample-project off"


def is_safe_session_id(value: str | None) -> bool:
    """True only for a short token we can safely use as a filename.

    The client echoes back the id we gave it, but it becomes a filename, so we
    reject anything that could escape the logs/ directory (slashes, dots, …)."""
    return bool(value) and re.fullmatch(r"[0-9A-Za-z-]{1,64}", value) is not None


def _first_user_message(messages: list[dict]) -> dict | None:
    for message in messages:
        if message.get("role") == "user":
            return message
    return None


def _smoke_command_text(messages: list[dict]) -> str | None:
    """Return the first user message if it is a smoke command, else None."""
    message = _first_user_message(messages)
    if not message:
        return None
    content = message.get("content")
    if not isinstance(content, str):
        return None
    text = content.strip()
    if text == SMOKE_COMMAND or text.startswith(SMOKE_COMMAND + " "):
        return text
    return None


def _is_smoke_command(messages: list[dict]) -> bool:
    """True when the first user message is any smoke-mode command."""
    return _smoke_command_text(messages) is not None


def _is_smoke_off_command(messages: list[dict]) -> bool:
    """True when the first user message is the smoke-mode off switch."""
    text = _smoke_command_text(messages)
    return bool(text) and (text == SMOKE_OFF_COMMAND or text.startswith(SMOKE_OFF_COMMAND + " "))


def _smoke_notice(sandbox: Path) -> str:
    return f"Smoke mode enabled. Ephemeral sandbox: {sandbox}."


def _smoke_off_notice() -> str:
    return "Smoke mode disabled. Using the normal project folder."


def _replace_command(messages: list[dict], notice: str) -> list[dict]:
    """Replace the first smoke command with a model-visible notice."""
    out: list[dict] = []
    replaced = False
    for message in messages:
        if message.get("role") == "system":
            continue
        msg = dict(message)
        if not replaced and msg.get("role") == "user" and isinstance(msg.get("content"), str):
            text = _smoke_command_text([msg])
            if text:
                rest = text[len(SMOKE_COMMAND):].strip()
                msg["content"] = notice
                if rest:
                    msg["content"] += f"\n\nFirst task: {rest}"
                replaced = True
        out.append(msg)
    return out


def _replace_smoke_command(messages: list[dict], sandbox: Path) -> list[dict]:
    """Replace the smoke-on command with the smoke notice."""
    return _replace_command(messages, _smoke_notice(sandbox))


def _replace_smoke_off_command(messages: list[dict]) -> list[dict]:
    """Replace the smoke-off command with the off notice."""
    return _replace_command(messages, _smoke_off_notice())


def _new_smoke_sandbox(session_id: str) -> str:
    """Create a disposable, inspectable sandbox under /tmp."""
    return tempfile.mkdtemp(
        prefix=f"wsh-smoke-{session_id[:8]}-",
        dir=Path(tempfile.gettempdir()),
    )


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Run the agent loop and stream events to the browser."""
    if not API_KEY:
        return StreamingResponse(
            iter([sse(ErrorEvent(type="error", message="Set DEEPSEEK_API_KEY first."))]),
            media_type="text/event-stream",
        )

    # One log file per session. Reuse the client's id when it's safe, otherwise
    # mint a fresh uuid — a session id becomes a filename, so never trust it.
    session_id = (
        req.session_id
        if req.session_id and is_safe_session_id(req.session_id)
        else str(uuid.uuid4())
    )
    log = SessionLog(session_id, logs_dir=LOGS_DIR)

    # Session-scoped smoke mode: the first message of a new session can turn this
    # session into a smoke run. Later turns resume the sandbox from the log header.
    smoke_command = _is_smoke_command(req.messages)
    smoke_off = _is_smoke_off_command(req.messages)
    is_new_session = not log.path.exists()
    if smoke_command and not smoke_off and is_new_session:
        log.sandbox = Path(_new_smoke_sandbox(session_id))
    elif smoke_off and not is_new_session and log.sandbox != SAMPLE_PROJECT:
        log.sandbox = SAMPLE_PROJECT
        log.write_sandbox(log.sandbox)

    system_prompt = make_system_prompt(log.sandbox)
    log.write_session(
        model=MODEL,
        base_url=BASE_URL,
        sandbox=str(log.sandbox),
        config={"max_steps": MAX_STEPS, "bash_timeout": BASH_TIMEOUT},
        system_prompt=system_prompt,
        tools=TOOLS,
    )

    # Strip any system message the client echoes back, then add ours exactly once.
    convo = [dict(m) for m in req.messages if m.get("role") != "system"]
    if smoke_off:
        convo = _replace_smoke_off_command(convo)
    elif smoke_command:
        convo = _replace_smoke_command(convo, log.sandbox)

    # Defensive: a `tool_calls` message must be followed by its `tool` replies.
    # Sessions replayed from a log where a turn died mid-flight can violate that
    # (the replayed `messages` are exactly what the UI echoes back). Drop the
    # tool_calls a second time here rather than letting history go unanswerable.
    dangling = _unanswered_tool_call_indexes(convo)
    for i in dangling:
        msg = dict(convo[i])
        msg.pop("tool_calls", None)
        if msg.get("content") is None:
            msg["content"] = ""
        convo[i] = msg

    messages = [{"role": "system", "content": system_prompt}] + convo
    stream = (sse(e) async for e in agent_loop(messages, log))
    return StreamingResponse(stream, media_type="text/event-stream")


@app.get("/api/sessions", response_model=SessionList)
async def list_sessions():
    """List available session logs, newest first. Read-only; no model calls."""
    sessions = []
    for path in LOGS_DIR.glob("*.jsonl"):
        if not is_safe_session_id(path.stem):
            continue
        meta = _session_meta(path)
        if meta is not None:
            sessions.append(meta)
    # The server owns ordering; the client renders in the order it receives.
    sessions.sort(key=lambda s: s["updated"], reverse=True)
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}", response_model=SessionPayload)
async def get_session(session_id: str):
    """Return one session's rebuilt UI state. Read-only; never calls the model."""
    if not is_safe_session_id(session_id):
        raise HTTPException(status_code=404, detail="unknown session")
    path = LOGS_DIR / f"{session_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="unknown session")
    payload = prepare_session(path)
    if not payload.messages:
        raise HTTPException(status_code=404, detail="empty session")
    return payload


@app.get("/api/health")
async def health():
    """Quick check that the server is up (and whether the key is set)."""
    return {"ok": True, "model": MODEL, "has_key": bool(API_KEY), "project": str(SAMPLE_PROJECT)}
