---
schema: "feature-load-jsonl-design"
branch: "feature/load-jsonl"
references:
  - doc: "feature-load-jsonl-UI-Mockup.md"
  - doc: "feature-load-jsonl-sequence.md"
  - doc: "feature-load-jsonl-plan.md"
---

# Load chat sessions from JSONL logs — design

## Why it's easy
Each log already holds everything needed. Concatenating `request.delta` + `response.message` in `seq`
order rebuilds the message list; tool calls (`response.message.tool_calls`) pair with their results (the
matching `role:"tool"` message). Opening and continuing a session is nearly free: the backend's
`SessionLog._resume()` already continues `seq` and avoids re-logging, so the UI only seeds `history` and
`sessionId` from the loaded session.

## Split
Grouping/rules live on the **backend** (pure, testable); the UI only renders. Each session payload returns
both `turns` (ready to render) and `messages` (echoed back to `/api/chat` to continue). No new deps.

## API
- `GET /api/sessions` → `{sessions:[{id, created_at, updated_at, user_turns, messages, preview}]}`,
  newest-first by `updated_at` (mtime fallback), empty files skipped.
- `GET /api/sessions/{id}` → `{session_id, model, started_at, messages, turns, warnings}`; 404 on
  unsafe/unknown/empty ids (guard with `is_safe_session_id`).

## Backend: `prepare_session(path)` (pure, read-only)
Rebuild `messages` from records (order by `seq`, tolerate bad lines), then group into `turns`: split on
`role:"user"`; assistant `tool_calls` → `Step{name,args,result}` keyed by `tool_call_id`; `role:"tool"`
fills the result; last **non-empty** assistant text = `answer`; empty answer → `incomplete:true`. Return
`messages` **without** the system message.

## UI
See `plans/feature-load-jsonl-UI-Mockup.md` for the layout mockup.

## Frontend
- Sidebar: timestamp-then-id items, newest-first, active highlight, "New chat", disabled while `busy`,
  collapse under ~720px.
- On mount load the list; if `?session=` present, auto-open. Selecting updates the URL, loads the session,
  replaces `turns`, sets `history.current = messages` and `sessionIdRef.current = id`. Reuse `<TurnView>`;
  show incomplete/error notes. "New chat" clears state + URL; refresh the list after a live send.

## Edge cases
Incomplete/error/partial turns shown with notes (never dropped); bad JSON lines skipped with a warning;
unsafe ids → 404.
