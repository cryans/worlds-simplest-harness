# World's Simplest Harness

A tiny coding harness you can actually understand end-to-end. You type a request
in a web page, a Python backend asks an LLM, and the LLM can run **bash** inside
a sandbox folder called `sample-project/` — reading, writing, and running files
until it finishes and answers you.

## The four moving pieces

| Piece | File | Job |
| --- | --- | --- |
| Web UI | `frontend/src/App.tsx` | A text box + a transcript |
| Backend | `backend/main.py` | FastAPI + the agent loop + tools |
| Sandbox | `sample-project/` | Where all `bash` runs |
| Model | DeepSeek API | The LLM that decides what to do |

## Where to start

1. [Getting Started](getting-started.md) — run it in two terminals.
2. [Architecture](architecture.md) — how a request flows through the harness.
3. [Tools](tools.md) — the `@tool` decorator and how to add your own tool.
4. [Smoke Test](smoke-test.md) — the manual end-to-end check to run after loop/SSE changes.
