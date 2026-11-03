"""Pydantic models — the single source of truth for the API's wire shapes.

This module is the enforced boundary: it imports pydantic only (plus stdlib) and
never config/tools/agent/session. Importing it must not read `.env`, create
directories, or touch the LLM client.
"""

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """What the web UI sends. `messages` is the raw OpenAI-format list, e.g.
    [{"role": "user", "content": "hi"}, {"role": "assistant", "content": ...}]
    It may also contain "tool" messages from previous turns.

    `session_id` is optional: the browser reuses the id the backend handed it,
    so a whole conversation lands in one log file. If absent (or unsafe), the
    backend mints a fresh uuid."""

    messages: list[dict] = []
    session_id: str | None = None


# --- API response models ----------------------------------------------------
# One source of truth for what the API returns (Pydantic -> OpenAPI -> TS).
# Field names and types are frozen: this is a type pass, not a wire-format change.

ToolResult = dict | str  # bash returns a dict; manage_plan returns a str


class ToolStep(BaseModel):
    """One tool invocation inside a turn. Shared vocabulary with the log's
    `response.message.tool_calls` (the log side is typed in a later feature)."""

    name: str
    args: dict = {}
    # `result` is what the tool returned: `bash` returns a dict
    # (exit_code/stdout/stderr), `manage_plan` returns a string.
    result: ToolResult | None = None


class SessionTurn(BaseModel):
    """One user message and everything the model did in response."""

    user: str
    steps: list[ToolStep] = []
    answer: str = ""
    error: str | None = None
    incomplete: bool = False


class SessionMeta(BaseModel):
    """Cheap metadata for the session list, derived (not stored) from a log."""

    id: str
    created: datetime | None = None
    updated: datetime | None = None
    created_at: str | None = None
    updated_at: str
    user_turns: int
    messages: int
    preview: str = ""


class SessionList(BaseModel):
    """Body of `GET /api/sessions`."""

    sessions: list[SessionMeta]


class SessionPayload(BaseModel):
    """Body of `GET /api/sessions/{id}` and the return of `prepare_session`."""

    session_id: str
    model: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    messages: list[dict] = []
    turns: list[SessionTurn] = []
    warnings: list[str] = []


# --- SSE event union ---------------------------------------------------------
# The `/api/chat` body is a stream, so these are *not* a route response_model.
# They describe what `sse()` emits; the contract is reflected into OpenAPI by the
# api layer's `custom_openapi` (one generation path, one diff check).


class SessionEvent(BaseModel):
    type: Literal["session"]
    session_id: str


class StatusEvent(BaseModel):
    type: Literal["status"]
    text: str


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"]
    name: str
    args: dict = {}


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"]
    name: str
    result: ToolResult


class AnswerEvent(BaseModel):
    type: Literal["answer"]
    session_id: str
    content: str = ""
    messages: list[dict] = []


class ErrorEvent(BaseModel):
    type: Literal["error"]
    message: str


SseEvent = Annotated[
    Union[SessionEvent, StatusEvent, ToolCallEvent, ToolResultEvent, AnswerEvent, ErrorEvent],
    Field(discriminator="type"),
]
