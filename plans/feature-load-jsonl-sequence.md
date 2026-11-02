---
schema: "feature-load-jsonl-sequence"
branch: "feature/load-jsonl"
references: []
---

# Load chat sessions from JSONL logs — sequence diagrams

Branch: `feature/load-jsonl` · Design: `plans/feature-load-jsonl-design.md`

Two flows. The key difference: **creating** a session puts the LLM in the loop (each model call is
write-ahead logged before it happens); **loading** one does not touch the LLM at all — it only reads the
log and rebuilds state. The LLM re-enters only when the user sends the first new message.

## 1. Session creation (LLM in the loop)

The browser POSTs the message history; the backend mints/reuses a session id, writes the `session` header
once, then for each step writes the `request` **before** calling the model (WAL) and the `response` after.
Tool calls loop back through the model until it answers in words; the final `answer` returns the updated
history the UI will echo back next turn.

```mermaid
sequenceDiagram
    autonumber
    participant UI as UI (browser)
    participant H as Harness (FastAPI)
    participant L as LLM (DeepSeek)
    participant S as SessionLog
    participant J as logs/{id}.jsonl

    UI->>H: POST /api/chat {messages, session_id?}
    H->>H: pick/reuse session id
    H->>S: SessionLog(id) (resume seq if file exists)
    S->>J: append "session" header (once)

    loop agent loop (until answer)
        H->>S: write_request(delta)  (write-ahead)
        S->>J: append "request" {seq, delta}
        H->>L: chat/completions (messages, tools)
        L-->>H: assistant message (tool_calls or content)
        H->>S: write_response(message, usage, latency)
        S->>J: append "response" {seq, message}
    end
    H-->>UI: SSE "answer" {content, messages}
```

## 2. Session (re)load (no LLM in the loop)

On mount (or deep-link `?session=<id>`) the UI lists and opens a session. The backend only **reads** the
log and rebuilds state; nothing is written and the LLM is not called. The UI seeds its history and
session id from the payload, so the next user message continues the same file — and only *then* does the
LLM re-enter (back to flow 1, appending to the existing log).

```mermaid
sequenceDiagram
    autonumber
    participant UI as UI (browser)
    participant H as Harness (FastAPI)
    participant S as SessionLog
    participant J as logs/{id}.jsonl

    Note over UI: page load / ?session=<id>
    UI->>H: GET /api/sessions
    H->>J: list *.jsonl (read ts, skip empty)
    H-->>UI: [{id, updated_at, …}] newest-first

    UI->>H: GET /api/sessions/{id}
    H->>S: prepare_session(path) (read-only)
    S->>J: read all records
    J-->>S: request/response/error lines
    S->>S: rebuild messages → group turns
    H-->>UI: {messages, turns, warnings}
    Note over UI: render turns, seed history and sessionId

    Note over UI,H: LLM is NOT called on load — until the first new message
    UI->>H: POST /api/chat {messages (seeded), session_id}
    Note over H,J: continues same file → flow 1
```
