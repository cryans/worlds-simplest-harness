---
status: "active"
---

# Recovery: tool-call failures are invisible

## What happened

A session run from our own harness failed on its **first tool call** with no
trace of the failure anywhere we knew to look — not in `logs/`, not in the UI,
nowhere. The symptom: the model returned a `tool_calls` response, and then the
stream silently ended with no `tool_result`, no `answer`, no `error`.

## Diagnosis

Three distinct problems stack up, all in the agent loop / session logging:

### 1. Tool execution has no error handling

In `backend/src/wsh/agent/loop.py`, model-call failures are handled explicitly:
the `try/except` around `call_model` writes a JSONL `error` record *and* streams
an `error` event to the browser. Tool calls have no such handling:

```python
yield ToolCallEvent(type="tool_call", name=name, args=args)
result = await call_tool(func, args)   # <-- no try/except
yield ToolResultEvent(type="tool_result", name=name, result=result)
```

If `call_tool` (or `run_bash`) raises, the exception propagates out of
`agent_loop`, through the `StreamingResponse` generator. Because the HTTP
response has already started streaming, FastAPI/Starlette/uvicorn logs the
traceback to the server's **console** and closes the stream silently. It never
touches `logs/`, and the browser just sees the stream end.

### 2. Tool events are never logged to JSONL at all

Even a *successful* run records **zero** `tool_call`/`tool_result` lines. Tools
are only streamed live (`ToolCallEvent`/`ToolResultEvent`); on disk they survive
only indirectly as a `"role": "tool"` message inside the *next* request's delta.
So a tool that fails and kills the stream leaves no record of itself anywhere.

### 3. Server stdout is lost when the launching shell is lost

The backend was started as a naked shell process; its console (where the only
copy of the traceback lives) was lost with the shell. There is no durable
server log.

## What we're doing here (deliberately not full SDLC)

This is a small, urgent bug fix — not a full feature. Skipping the normal
requirements → design → plan → implement → retro ceremony; jumping straight to
a focused fix and its tests.

### Fix scope

1. Wrap tool dispatch in `try/except` so a tool exception:
   - is surfaced to the browser as a `tool_result` carrying an `error` payload
     (rather than killing the stream), and
   - is written to the JSONL via `log.write_error(...)` so it survives and
     replays like model errors do.
2. Capture the backend's stdout/stderr to a durable file (`logs/uvicorn.log`)
   so the server console is never lost again:
   - `backend/start.sh` — starts uvicorn with output redirected to
     `logs/uvicorn.log`, a writable `UV_CACHE_DIR`, and `mkdir -p logs/`.
   - `backend/stop.sh` — kills both the `--reload` parent *and* its supervised
     server worker, since `--reload` runs two processes.

### Out of scope for this branch

- Fully logging `tool_call`/`tool_result` events as first-class JSONL records.
  That's a larger logging-shape change and belongs to its own feature.
- `harness-guardrails` (ruff/mypy/pre-commit, `MAX_TOOL_OUTPUT_CHARS`) — tracked
  separately in `plans/next-steps.md`.

## Open questions

- Pin the *specific* exception that killed the first tool call (was it the
  `create_subprocess_shell(cwd=SAMPLE_PROJECT)` path? something else?). The
  traceback lives only in the now-lost console; the restart with `uvicorn.log`
  should capture it on the next reproduction.
