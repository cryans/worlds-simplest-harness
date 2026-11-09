"""The HTTP endpoints: chat (SSE stream), session list/detail, and health."""

import re
import uuid

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from wsh.agent import agent_loop
from wsh.api.app import app
from wsh.config import (
    API_KEY,
    BASE_URL,
    BASH_TIMEOUT,
    LOGS_DIR,
    MAX_STEPS,
    MODEL,
    SAMPLE_PROJECT,
)
from wsh.models import ChatRequest, ErrorEvent, SessionList, SessionPayload
from wsh.plugins import PluginRequirementError, resolve_session, set_current_session
from wsh.session import SessionLog, _session_meta, prepare_session
from wsh.sse import sse


def is_safe_session_id(value: str | None) -> bool:
    """True only for a short token we can safely use as a filename.

    The client echoes back the id we gave it, but it becomes a filename, so we
    reject anything that could escape the logs/ directory (slashes, dots, …)."""
    return bool(value) and re.fullmatch(r"[0-9A-Za-z-]{1,64}", value) is not None


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

    # Resolve the session context (normal or a plugin). A plugin whose
    # requirements aren't met refuses the mode up front with an error.
    try:
        ctx = resolve_session(req.messages, log)
    except PluginRequirementError as exc:
        return StreamingResponse(
            iter([sse(ErrorEvent(type="error", message=str(exc)))]),
            media_type="text/event-stream",
        )

    log.sandbox = ctx.sandbox
    log.mode = ctx.mode
    log.write_session(
        model=MODEL,
        base_url=BASE_URL,
        sandbox=str(ctx.sandbox),
        mode=ctx.mode,
        config={"max_steps": MAX_STEPS, "bash_timeout": BASH_TIMEOUT},
        system_prompt=ctx.system_prompt,
        tools=ctx.tools,
    )

    async def stream_with_context():
        # Set the context inside the stream task so the loop/client see it.
        set_current_session(ctx)
        async for event in agent_loop(ctx.messages, log):
            yield event

    stream = (sse(e) async for e in stream_with_context())
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
