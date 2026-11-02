"""
The world's simplest coding harness — backend.

One file, three ideas:

  1.  A FastAPI app with ONE endpoint:  POST /api/chat
  2.  That endpoint runs an "agent loop":
        - send the conversation to the model
        - if the model asks to run a tool, run it inside sample-project/
        - feed the tool's output back to the model
        - repeat until the model answers in plain words
  3.  Everything is streamed to the web UI as Server-Sent Events (SSE),
      so you can watch the loop happen in real time.

Tools are registered with the @tool decorator (see the "tool registry"
section below): a function's name, docstring, and type hints are turned
into the model-facing schema automatically.

Run it with:
    cd backend
    uv venv && source .venv/bin/activate
    uv pip install -r requirements.txt
    DEEPSEEK_API_KEY=... uvicorn main:app --reload --port 8010
"""

import asyncio
import inspect
import json
import os
import re
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, get_type_hints

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, create_model

# --- config ---------------------------------------------------------------

load_dotenv()  # reads backend/.env if it exists, so you don't have to export keys

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
MAX_STEPS = int(os.environ.get("MAX_STEPS", "100"))  # how many model<->tool round-trips
BASH_TIMEOUT = int(os.environ.get("BASH_TIMEOUT", "30"))  # seconds per bash command

# The sandbox folder. It lives at the repo ROOT, next to backend/ and frontend/.
SAMPLE_PROJECT = (Path(__file__).resolve().parent.parent / "sample-project").resolve()
SAMPLE_PROJECT.mkdir(exist_ok=True)

# Session logs: one append-only JSONL file per session, at the repo ROOT.
LOGS_DIR = (Path(__file__).resolve().parent.parent / "logs").resolve()

# --- the app ---------------------------------------------------------------

app = FastAPI(title="World's Simplest Harness")

# Allow the Vite dev server (http://localhost:5173) to call us directly.
# (We ALSO set up a Vite proxy, so this is just a safety net.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- the model's instructions ---------------------------------------------

SYSTEM_PROMPT = f"""
You are a helpful coding assistant with access to ONE tool: `bash`.

Rules:
- `bash` runs a single command inside the project folder ({SAMPLE_PROJECT}).
- Use it to inspect files, create files, edit them, and run them.
- You may use it several times. After each command you will see its output.
- When you are finished, reply to the user in plain text. Do NOT call bash again.

Think step by step, and keep commands short and focused.
""".strip()

# --- the @tool decorator ---------------------------------------------------

# What we send to the model: one entry per registered tool.
TOOLS: list[dict] = []

# Name -> the actual function, so the agent loop can call the right one.
TOOL_REGISTRY: dict[str, Callable] = {}


def tool(func: Callable) -> Callable:
    """Register a function as a callable tool.

    Reads the function's name, docstring, and type hints to generate the
    OpenAI "tool calling" schema automatically — the same shape that used to
    be written by hand.
    """
    name = func.__name__
    description = (func.__doc__ or "").strip()

    # Resolve type hints, dropping the return annotation (not a parameter).
    hints = get_type_hints(func)
    hints.pop("return", None)

    # Build a pydantic model from the parameters; it generates the JSON Schema.
    fields: dict[str, Any] = {}
    for param_name, param in inspect.signature(func).parameters.items():
        field_type = hints.get(param_name, Any)
        if param.default is inspect.Parameter.empty:
            fields[param_name] = (field_type, ...)            # required
        else:
            fields[param_name] = (field_type, param.default)  # optional

    parameters = create_model(name, **fields).model_json_schema()

    # The same information feeds two consumers:
    TOOL_REGISTRY[name] = func  # the agent loop calls it by name
    TOOLS.append(                # the model reads its schema
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
    )
    return func


# --- helpers ----------------------------------------------------------------

class ChatRequest(BaseModel):
    """What the web UI sends. `messages` is the raw OpenAI-format list, e.g.
    [{"role": "user", "content": "hi"}, {"role": "assistant", "content": ...}]
    It may also contain "tool" messages from previous turns.

    `session_id` is optional: the browser reuses the id the backend handed it,
    so a whole conversation lands in one log file. If absent (or unsafe), the
    backend mints a fresh uuid."""

    messages: list[dict] = []
    session_id: str | None = None


def sse(event: str, data: dict) -> str:
    """Encode one event for the browser as a Server-Sent Event.
    The type is repeated inside the JSON so the browser can parse it easily."""
    return f"event: {event}\ndata: {json.dumps({**data, 'type': event})}\n\n"


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string (with timezone)."""
    return datetime.now(timezone.utc).isoformat()


def is_safe_session_id(value: str | None) -> bool:
    """True only for a short token we can safely use as a filename.

    The client echoes back the id we gave it, but it becomes a filename, so we
    reject anything that could escape the logs/ directory (slashes, dots, …)."""
    return bool(value) and re.fullmatch(r"[0-9A-Za-z-]{1,64}", value) is not None


class SessionLog:
    """Append-only, write-ahead JSONL log for one session.

    One JSON object per line. Every line is an immutable event with a
    monotonically-increasing ``seq`` (the WAL sequence number), a UTC ``ts``,
    the ``session`` id, and a ``type``. Replaying the file in order
    reconstructs exactly what went to the model — without ever re-serialising
    the whole history: each ``request`` line carries only the NEW messages
    since the previous one (its *delta*), never ``[m1]``, ``[m1, m2]``, …
    """

    def __init__(self, session_id: str, logs_dir: Path = LOGS_DIR):
        self.session_id = session_id
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.path = logs_dir / f"{session_id}.jsonl"
        self._seq, self._logged = self._resume()

    def _resume(self) -> tuple[int, int]:
        """Scan an existing file to continue where it left off.

        Returns ``(next_seq, logged_messages)``. ``logged_messages`` is the
        highest ``total_messages`` already written, so a history replayed by
        the browser is never logged twice. Torn/partial trailing lines are
        ignored (they are the cost of a crash mid-append, which we don't try
        to repair).
        """
        next_seq = 0
        logged = 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                next_seq = max(next_seq, int(rec.get("seq", -1)) + 1)
                logged = max(logged, int(rec.get("total_messages", 0) or 0))
        return next_seq, logged

    def _append(self, record: dict) -> None:
        """Stamp the envelope and append one line. Never rewrites earlier lines."""
        record["seq"] = self._seq
        record["ts"] = now_iso()
        record["session"] = self.session_id
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        self._seq += 1

    def write_session(self, model, base_url, sandbox, config, system_prompt, tools) -> None:
        """The one-time header: static config, so it isn't repeated per request."""
        if self._seq != 0:  # header already written for an existing file
            return
        self._append(
            {
                "type": "session",
                "model": model,
                "base_url": base_url,
                "sandbox": sandbox,
                "config": config,
                "system_prompt": system_prompt,
                "tools": tools,
            }
        )

    def write_request(self, convo: list[dict], step: int, model: str) -> None:
        """Log the model request. ``convo`` has the system message at [0]; the
        delta is only the conversation messages added since the last request."""
        msgs = convo[1:]  # the system message is captured in the header
        # `_logged` is the number of messages the *file* says are already known.
        # A failed/aborted turn changes the conversation without the matching
        # messages ever reaching the file, so trust the client's history as the
        # source of truth whenever it disagrees: replay stays aligned with what
        # the next request actually sends.
        if len(msgs) < self._logged:
            self._logged = len(msgs)
        delta = msgs[self._logged :]
        self._logged = len(msgs)
        self._append(
            {
                "type": "request",
                "step": step,
                "model": model,
                "delta": delta,
                "total_messages": len(msgs),
            }
        )

    def write_response(self, message, step, model, latency_ms, finish_reason, usage) -> None:
        """Log the model's reply (also counts as one more logged message)."""
        self._logged += 1
        self._append(
            {
                "type": "response",
                "step": step,
                "model": model,
                "latency_ms": latency_ms,
                "finish_reason": finish_reason,
                "message": message,
                "usage": usage,
                "total_messages": self._logged,
            }
        )

    def write_error(self, message: str, step: int) -> None:
        """Log a failed model call (its request line is already on disk)."""
        self._append({"type": "error", "step": step, "message": message})


# --- reading session logs back into UI state ------------------------------


def read_records(path: Path) -> tuple[list[dict], int]:
    """Read a JSONL file into ``(records, skipped)``.

    Records are returned in file order (which is ``seq`` order). Blank lines and
    lines that aren't valid JSON (e.g. a torn trailing write after a crash) are
    skipped and counted, never raised.
    """
    records: list[dict] = []
    skipped = 0
    if not path.exists():
        return records, skipped
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(rec, dict):
            records.append(rec)
        else:
            skipped += 1
    return records, skipped


def _parse_json_arg(value: Any, default: Any) -> Any:
    """Tool args/results are JSON strings in the log; decode defensively."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _unanswered_tool_call_indexes(messages: list[dict]) -> list[int]:
    """Indexes of assistant messages whose ``tool_calls`` lack replies.

    A message is dangling when any of its ``tool_call_id``s has no ``tool``
    message in the run of messages immediately following it (the OpenAI wire
    format requires the replies to be adjacent, in any order).
    """
    dangling: list[int] = []
    for i, msg in enumerate(messages):
        ids = {tc.get("id") for tc in (msg.get("tool_calls") or []) if isinstance(tc, dict)}
        ids.discard(None)
        if msg.get("role") != "assistant" or not ids:
            continue
        answered: set = set()
        for nxt in messages[i + 1 :]:
            if nxt.get("role") != "tool":
                break
            answered.add(nxt.get("tool_call_id"))
            if ids <= answered:
                break
        if not ids <= answered:
            dangling.append(i)
    return dangling


def prepare_session(path: Path) -> dict:
    """Rebuild UI-only state from a session log. Read-only; never calls the model.

    Concatenates every ``request.delta`` and ``response.message`` in order to
    rebuild the OpenAI-format message list (system message excluded), then groups
    it into ``turns`` shaped like the frontend's ``Turn``:

        {user, steps: [{name, args, result}], answer, error?, incomplete?}

    Tolerates malformed input: bad lines are skipped (and warned about), unknown
    roles are ignored, and orphan tool results are dropped from rendering.
    """
    records, skipped = read_records(path)
    warnings: list[str] = []
    if skipped:
        warnings.append(f"skipped {skipped} unreadable line(s)")

    header: dict = {}
    messages: list[dict] = []
    errors_by_step: dict[int, str] = {}

    for rec in records:
        rtype = rec.get("type")
        if rtype == "session":
            header = rec
        elif rtype == "request":
            delta = rec.get("delta") or []
            if isinstance(delta, list):
                messages.extend(m for m in delta if isinstance(m, dict))
        elif rtype == "response":
            msg = rec.get("message")
            if isinstance(msg, dict):
                messages.append(msg)
        elif rtype == "error":
            errors_by_step[rec.get("step", -1)] = rec.get("message", "error")

    # Logs written before null-coercion existed can carry `content: null` on an
    # assistant tool-call turn; the OpenAI wire format wants a string there.
    for msg in messages:
        if msg.get("content") is None:
            msg["content"] = ""

    # A request is logged write-ahead, *before* the model call. If that call
    # failed (or the turn is still running), the last assistant message asks for
    # tools whose results were never logged. Such a conversation is invalid for
    # the model: every `tool_calls` id must have a matching `tool` message. Two
    # cases, both repaired by dropping the outgoing assistant's tool_calls:
    #   * the request is the final message  -> prose + finish_reason=stop
    #   * later messages exist (the user already sent a new turn) -> native
    #     "continue" assistant turn, so the pending user message still answers it
    dangling = _unanswered_tool_call_indexes(messages)
    if dangling:
        warnings.append(
            f"{len(dangling)} assistant request(s) without tool results; dropped their tool calls"
        )
        final = len(messages) >= 1 and dangling[-1] == len(messages) - 1
        for i in dangling:
            msg = dict(messages[i])
            msg.pop("tool_calls", None)
            content = msg.get("content")
            if final and i == dangling[-1]:
                msg["role"] = "assistant"
                msg["content"] = content or "I was about to run a command, but the request failed."
            elif not (content or "").strip():
                msg["role"] = "assistant"
                msg["content"] = "Continuing."
            messages[i] = msg

    # Group messages into turns, splitting on user messages.
    turns: list[dict] = []
    current: dict | None = None
    steps_by_id: dict[str, dict] = {}

    def _new_turn(user: str) -> dict:
        return {"user": user, "steps": [], "answer": "", "error": None}

    for msg in messages:
        role = msg.get("role")
        if role == "user":
            if current is not None:
                turns.append(current)
            current = _new_turn(msg.get("content") or "")
            steps_by_id = {}
        elif role == "assistant":
            if current is None:
                current = _new_turn("")  # assistant with no preceding user msg
            for tc in msg.get("tool_calls") or []:
                fn = (tc or {}).get("function") or {}
                step = {
                    "name": fn.get("name"),
                    "args": _parse_json_arg(fn.get("arguments"), {}),
                    "result": None,
                }
                tc_id = (tc or {}).get("id")
                if tc_id:
                    steps_by_id[tc_id] = step
                current["steps"].append(step)
            content = (msg.get("content") or "").strip()
            if content:
                current["answer"] = msg.get("content")
        elif role == "tool":
            step = steps_by_id.get(msg.get("tool_call_id"))
            if step is not None:
                step["result"] = _parse_json_arg(msg.get("content"), {})
            elif current is not None:
                warnings.append("orphan tool result ignored")
        # unknown roles are ignored

    if current is not None:
        turns.append(current)

    # Attach the most recent error (if any) to the final turn, then mark turns
    # that produced no answer text as incomplete.
    if errors_by_step and turns:
        turns[-1]["error"] = errors_by_step[max(errors_by_step)]
    for turn in turns:
        if not turn["answer"] and not turn["error"]:
            turn["incomplete"] = True

    started = records[0].get("ts") if records else None
    updated = records[-1].get("ts") if records else None

    return {
        "session_id": header.get("session") or path.stem,
        "model": header.get("model"),
        "started_at": started,
        "updated_at": updated,
        "messages": messages,
        "turns": turns,
        "warnings": warnings,
    }


async def run_bash(command: str) -> dict:
    """Run a shell command inside sample-project/ and capture its output."""
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=SAMPLE_PROJECT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=BASH_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {"exit_code": None, "stdout": "", "stderr": f"(timed out after {BASH_TIMEOUT}s)"}

    return {
        "exit_code": proc.returncode,
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
    }


async def call_tool(func: Callable, args: dict):
    """Call a registered tool with parsed args, awaiting if it's a coroutine."""
    result = func(**args)
    if inspect.iscoroutine(result):
        result = await result
    return result


@tool
async def bash(command: str) -> dict:
    """Run a bash command inside the project folder. Use it to read, write, and run files there."""
    return await run_bash(command)

@tool
def manage_plan(filename: str, content: str, mode: str = "write") -> str:
    """
    Manage an agent plan or todo list as a plain markdown file.
    
    Args:
        filename: Path to the markdown file (e.g., 'plan.md' or 'todo.md').
        content: The markdown content or task updates to write/append.
        mode: Operation mode - 'write' (overwrite/create), 'append' (add to end), or 'read'.
        
    Returns:
        Status message or current content of the file.
    """
    try:
        # Ensure we stay safe in the current workspace directory
        filepath = os.path.normpath(filename)

        if mode == "read":
            if not os.path.exists(filepath):
                return f"Plan file '{filename}' does not exist yet."
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()

        elif mode == "append":
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(f"\n{content}")
            return f"Successfully appended update to '{filename}'."

        elif mode == "write":
            # Ensure target parent directories exist
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully saved plan to '{filename}'."

        else:
            return f"Error: Invalid mode '{mode}'. Choose 'write', 'append', or 'read'."

    except Exception as e:
        return f"Failed to perform '{mode}' operation on '{filename}': {str(e)}"


async def call_model(messages: list[dict]) -> dict:
    """One non-streaming call to DeepSeek. Returns the raw response JSON."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"model": MODEL, "messages": messages, "tools": TOOLS},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()


# --- the agent loop ---------------------------------------------------------

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


# --- the endpoint -----------------------------------------------------------

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Run the agent loop and stream events to the browser."""
    if not API_KEY:
        return StreamingResponse(
            iter([sse("error", {"message": "Set DEEPSEEK_API_KEY first."})]),
            media_type="text/event-stream",
        )

    # One log file per session. Reuse the client's id when it's safe, otherwise
    # mint a fresh uuid — a session id becomes a filename, so never trust it.
    session_id = (
        req.session_id
        if req.session_id and is_safe_session_id(req.session_id)
        else str(uuid.uuid4())
    )
    log = SessionLog(session_id)
    log.write_session(
        model=MODEL,
        base_url=BASE_URL,
        sandbox=str(SAMPLE_PROJECT),
        config={"max_steps": MAX_STEPS, "bash_timeout": BASH_TIMEOUT},
        system_prompt=SYSTEM_PROMPT,
        tools=TOOLS,
    )

    # Strip any system message the client echoes back, then add ours exactly once.
    convo = [m for m in req.messages if m.get("role") != "system"]

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

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + convo
    return StreamingResponse(agent_loop(messages, log), media_type="text/event-stream")


# Timestamps in a log are ISO-8601 with an offset (``...T15:06:36+00:00``).
# Compare them as datetimes, never as strings: two equal-looking strings can
# carry different offsets, and naive-vs-aware comparison would raise anyway.

def _parse_ts(value: Any) -> datetime | None:
    """Parse one log timestamp into an aware UTC datetime (None if unusable)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:  # treat a missing offset as UTC, as the log intends
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _updated_at(records: list[dict], path: Path) -> datetime:
    """When the session last did anything: newest record, else file mtime.

    The mtime fallback covers a header-only log (one write, no records with a
    ``ts`` we can read) so such a session still sorts sensibly instead of
    being pinned to the epoch. ``st_mtime`` is already real system time.
    """
    stamps = [ts for ts in (_parse_ts(r.get("ts")) for r in records) if ts is not None]
    if stamps:
        return max(stamps)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _session_meta(path: Path) -> dict | None:
    """Cheap metadata for the session list, or None for an empty/unusable file."""
    records, _ = read_records(path)
    if not records:
        return None
    user_turns = sum(
        1
        for rec in records
        if rec.get("type") == "request"
        for m in (rec.get("delta") or [])
        if isinstance(m, dict) and m.get("role") == "user"
    )
    preview = ""
    for rec in records:
        if rec.get("type") == "request":
            for m in rec.get("delta") or []:
                if isinstance(m, dict) and m.get("role") == "user":
                    preview = (m.get("content") or "")[:120]
                    break
            if preview:
                break
    parent = records[0] if records else {}
    updated = _updated_at(records, path)
    return {
        "id": parent.get("session") or path.stem,
        # `created`/`updated` are real datetimes: the server sorts on them, so
        # ordering never depends on comparing strings or on every timestamp
        # sharing one UTC offset. `updated_at` is the same instant rendered for
        # the UI label (ISO-8601 UTC); clients must not sort on it.
        "created": _parse_ts(parent.get("ts")),
        "updated": updated,
        "created_at": parent.get("ts"),
        "updated_at": updated.isoformat(),
        "user_turns": user_turns,
        "messages": max((int(r.get("total_messages", 0) or 0) for r in records), default=0),
        "preview": preview,
    }


@app.get("/api/sessions")
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


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """Return one session's rebuilt UI state. Read-only; never calls the model."""
    if not is_safe_session_id(session_id):
        raise HTTPException(status_code=404, detail="unknown session")
    path = LOGS_DIR / f"{session_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="unknown session")
    payload = prepare_session(path)
    if not payload["messages"]:
        raise HTTPException(status_code=404, detail="empty session")
    return payload


@app.get("/api/health")
async def health():
    """Quick check that the server is up (and whether the key is set)."""
    return {"ok": True, "model": MODEL, "has_key": bool(API_KEY), "project": str(SAMPLE_PROJECT)}
