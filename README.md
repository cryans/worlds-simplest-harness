# World's Simplest Harness

A tiny coding harness you can actually understand end-to-end. You type a request
in a web page, a Python backend asks an LLM, and the LLM can run **bash** inside
a sandbox folder called `sample-project/` — reading, writing, and running files
until it finishes and answers you.

## The pieces

```
worlds-simplest-harness/
├── frontend/         React + Vite (TypeScript) web UI
│   └── src/App.tsx   the whole UI: a chat box + a transcript
├── backend/
│   ├── main.py       thin entrypoint: `from wsh.api.app import app`
│   ├── pyproject.toml  deps + build (uv)
│   └── src/wsh/      config, models, tools, session, agent, api
├── sample-project/   THE sandbox. All bash runs in here.
├── .env.example      copy → backend/.env and add your key
└── README.md         you are here
```

### How the agent loop works

This is the one idea that matters. The backend does this, in a loop (in `backend/src/wsh/agent/loop.py`):

1. Send the conversation to the model (DeepSeek), telling it about one tool: `bash`.
2. If the model replies in words → done, stream the answer to the browser.
3. If the model replies with a `bash` tool call → run that command in
   `sample-project/`, capture its output, feed that output back to the model,
   and go back to step 1.

Each step is streamed to the browser as a Server-Sent Event (`status`,
`tool_call`, `tool_result`, `answer`), so you can watch it happen.

## Run it

### 1. Backend

```bash
cp .env.example backend/.env      # then edit it: put in your DEEPSEEK_API_KEY

cd backend
uv sync                           # install deps + the `wsh` package (uv is already installed)
uv run uvicorn main:app --reload --port 8010
```

Check it's alive: http://localhost:8010/api/health

### 2. Frontend (separate terminal)

```bash
cd frontend
pnpm install
pnpm dev
```

Open http://localhost:5173 — Vite proxies `/api` to the backend on port 8010.

### 3. Try it

Type: **"Create a Python script that prints the first 20 Fibonacci numbers, then run it."**

You'll see the model run `bash` commands (writing and running a file inside
`sample-project/`), and the file will actually appear there. Open the folder to
see it.

## Session logs

Every conversation is tagged with a **session id** (a `uuid`). On the first
turn the backend mints one and streams it to the browser in a `session` event;
the browser echoes it back, so a whole conversation lands in a single file:

```
logs/{session-id}.jsonl
```

The file is **append-only and write-ahead** (WAL style): one JSON object per
line, appended one line at a time, never rewritten. Each line is a self-contained
event with a monotonic `seq`, a UTC `ts`, the `session` id, and a `type`.
Replay the file top-to-bottom to reconstruct exactly what went to the model.

Crucially, it is **not cumulative** — a `request` line carries only the *new*
messages since the previous request (its **delta**), never `[m1]`, `[m1, m2]`,
`[m1, m2, m3]`:

| `type`     | When                                            | Carries                                                        |
| ---------- | ----------------------------------------------- | -------------------------------------------------------------- |
| `session`  | once, on a new session file                     | model, base URL, sandbox, config, system prompt, tool schemas  |
| `request`  | before each model call (write-ahead)            | `delta` (new messages), `step`, `total_messages`               |
| `response` | after each successful model call                | the assistant message, `usage`, `finish_reason`, `latency_ms`  |
| `error`    | when a model call fails                         | the error message                                              |

Example (three lines of one file):

```json
{"seq":0,"ts":"2026-01-15T12:00:00.000000+00:00","session":"9f8e…","type":"session","model":"deepseek-chat","system_prompt":"…","tools":[…]}
{"seq":1,"ts":"…","session":"9f8e…","type":"request","step":1,"model":"deepseek-chat","delta":[{"role":"user","content":"hi"}],"total_messages":1}
{"seq":2,"ts":"…","session":"9f8e…","type":"response","step":1,"model":"deepseek-chat","latency_ms":1234,"finish_reason":"stop","message":{"role":"assistant","content":"hello!"},"usage":{…},"total_messages":2}
```

The `logs/` directory is git-ignored.

## What's deliberately left out

- No streaming of the model's own tokens (we stream *harness* events instead).
- No server-side conversation memory — the browser still sends the full history
  each turn (the backend just tags it with a session id and logs it, and
  returns the updated history in the `answer` event).
- One tool only. Everything else is "read/write files" done via `bash`.

Add those one at a time once this makes sense.

## Config

All via environment variables (or `backend/.env`):

| Var                 | Default                   | What it does                        |
| ------------------- | ------------------------- | ----------------------------------- |
| `DEEPSEEK_API_KEY`  | *(required)*              | Your DeepSeek API key               |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com`| API endpoint                        |
| `DEEPSEEK_MODEL`    | `deepseek-chat`           | Model name                          |
| `MAX_STEPS`         | `10`                      | Max model↔tool round-trips per turn |
| `BASH_TIMEOUT`      | `30`                      | Seconds before a bash command is killed |
