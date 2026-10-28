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
from collections.abc import Callable
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
MAX_STEPS = int(os.environ.get("MAX_STEPS", "10"))  # how many model<->tool round-trips
BASH_TIMEOUT = int(os.environ.get("BASH_TIMEOUT", "30"))  # seconds per bash command

# The sandbox folder. It lives at the repo ROOT, next to backend/ and frontend/.
SAMPLE_PROJECT = (Path(__file__).resolve().parent.parent / "sample-project").resolve()
SAMPLE_PROJECT.mkdir(exist_ok=True)

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
    It may also contain "tool" messages from previous turns."""

    messages: list[dict] = []


def sse(event: str, data: dict) -> str:
    """Encode one event for the browser as a Server-Sent Event.
    The type is repeated inside the JSON so the browser can parse it easily."""
    return f"event: {event}\ndata: {json.dumps({**data, 'type': event})}\n\n"


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

async def agent_loop(messages: list[dict]):
    """
    The whole point of a harness. Yields SSE strings for the browser.

    Steps:
      1. ask the model
      2. no tool calls? -> stream the answer and stop
      3. tool calls? -> look each one up in TOOL_REGISTRY, run it,
         stream its result, append a 'tool' message, and go back to step 1
    """
    # Work on a copy so the caller's list isn't mutated by surprise.
    convo = [dict(m) for m in messages]

    for _ in range(MAX_STEPS):
        yield sse("status", {"text": "asking the model…"})

        try:
            data = await call_model(convo)
        except httpx.HTTPStatusError as e:
            yield sse("error", {"message": f"Model error: {e.response.status_code} {e.response.text}"})
            return
        except Exception as e:  # network failure, bad key, etc.
            yield sse("error", {"message": f"Could not reach the model: {e}"})
            return

        choice = data["choices"][0]["message"]
        # Keep the assistant's message in the conversation, including tool_calls.
        convo.append(choice)

        tool_calls = choice.get("tool_calls") or []
        if not tool_calls:
            # The model is done. Send the answer plus the NEW full history,
            # so the web UI can send it back next turn.
            yield sse(
                "answer",
                {"content": choice.get("content") or "", "messages": convo},
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

    yield sse("answer", {"content": f"(stopped after {MAX_STEPS} steps)", "messages": convo})


# --- the endpoint -----------------------------------------------------------

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Run the agent loop and stream events to the browser."""
    if not API_KEY:
        return StreamingResponse(
            iter([sse("error", {"message": "Set DEEPSEEK_API_KEY first."})]),
            media_type="text/event-stream",
        )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + req.messages
    return StreamingResponse(agent_loop(messages), media_type="text/event-stream")


@app.get("/api/health")
async def health():
    """Quick check that the server is up (and whether the key is set)."""
    return {"ok": True, "model": MODEL, "has_key": bool(API_KEY), "project": str(SAMPLE_PROJECT)}
