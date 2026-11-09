"""Plugin seam: a session-scoped context for tools, prompt, sandbox, and messages.

The chat route resolves one `SessionContext` per request and sets it for the
duration of the stream. The agent loop and model client read `tools`/`registry`
from here instead of importing the module-level globals, so a plugin can offer a
different tool set (e.g. smoke mode's bwrap `bash`) without the loop knowing.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from wsh.config import SAMPLE_PROJECT, make_system_prompt
from wsh.session import sanitize_messages
from wsh.tools import TOOL_REGISTRY, TOOLS


class PluginRequirementError(Exception):
    """A plugin's declared requirements are not met; the mode must not turn on."""


@dataclass
class SessionContext:
    mode: str
    sandbox: Path
    system_prompt: str
    tools: list[dict]
    registry: dict[str, Callable]
    messages: list[dict]


_current_session: ContextVar[SessionContext | None] = ContextVar(
    "wsh_session_context", default=None
)


def set_current_session(ctx: SessionContext) -> None:
    """Set the session context for the current task (read by loop/client)."""
    _current_session.set(ctx)


def get_current_tools() -> list[dict]:
    """The model tool schema for the current session, or the global default."""
    ctx = _current_session.get()
    return ctx.tools if ctx is not None else TOOLS


def get_current_registry() -> dict[str, Callable]:
    """The name -> callable dispatch map for the current session, or the global default."""
    ctx = _current_session.get()
    return ctx.registry if ctx is not None else TOOL_REGISTRY


def assemble_messages(raw_messages: list[dict], system_prompt: str, rewriter=None) -> list[dict]:
    """Build the final message list for a turn.

    Drops any system message the client echoes back, applies the optional
    mode-specific rewriter, enforces the OpenAI wire invariants (dangling
    ``tool_calls`` dropped, orphan/duplicate ``tool`` replies dropped, no
    ``content: None``), and prepends our system prompt exactly once.
    """
    convo = [dict(m) for m in raw_messages if m.get("role") != "system"]
    if rewriter is not None:
        convo = rewriter(convo)
    convo = sanitize_messages(convo)
    return [{"role": "system", "content": system_prompt}] + convo


def normal_context(raw_messages: list[dict], rewriter=None) -> SessionContext:
    """The unchanged normal-mode context: default sandbox, prompt, and both tools."""
    prompt = make_system_prompt(SAMPLE_PROJECT)
    return SessionContext(
        mode="normal",
        sandbox=SAMPLE_PROJECT,
        system_prompt=prompt,
        tools=TOOLS,
        registry=dict(TOOL_REGISTRY),
        messages=assemble_messages(raw_messages, prompt, rewriter),
    )


def resolve_session(raw_messages: list[dict], log) -> SessionContext:
    """Resolve the session context for this request (first matching plugin, else
    normal mode).

    Plugins register themselves via ``register_plugin``; ``resolve_session``
    asks each in registration order whether it ``matches`` and, if so, lets it
    ``prepare`` the context. With no plugins registered (the seam on its own),
    every session is the normal context.
    """
    for plugin in _plugins:
        if plugin.matches(raw_messages, log):
            return plugin.prepare(raw_messages, log)
    return normal_context(raw_messages)


def register_plugin(plugin) -> None:
    """Register a plugin for resolution. Called by a plugin's own module on import."""
    _plugins.append(plugin)


_plugins: list = []
