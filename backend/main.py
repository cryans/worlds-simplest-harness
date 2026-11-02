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
from fastapi import FastAPI
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
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + [
        m for m in req.messages if m.get("role") != "system"
    ]
    return StreamingResponse(agent_loop(messages, log), media_type="text/event-stream")


@app.get("/api/health")
async def health():
    """Quick check that the server is up (and whether the key is set)."""
    return {"ok": True, "model": MODEL, "has_key": bool(API_KEY), "project": str(SAMPLE_PROJECT)}
