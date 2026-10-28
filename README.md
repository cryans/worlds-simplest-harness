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
│   ├── main.py       FastAPI app + the "agent loop" + the bash tool
│   └── requirements.txt
├── sample-project/   THE sandbox. All bash runs in here.
├── .env.example      copy → backend/.env and add your key
└── README.md         you are here
```

### How the agent loop works

This is the one idea that matters. `backend/main.py` does this, in a loop:

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
uv venv                           # create a virtualenv (uv is already installed)
source .venv/bin/activate
uv pip install -r requirements.txt
uvicorn main:app --reload --port 8010
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

## What's deliberately left out

- No streaming of the model's own tokens (we stream *harness* events instead).
- No sessions / memory in the backend — the browser sends the full history each
  time, and the backend returns the updated history in the `answer` event.
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
