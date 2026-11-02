---
schema: "feature-load-jsonl-plan"
branch: "feature/load-jsonl"
references: []
---

# Load chat sessions from JSONL logs — implementation plan

Branch: `feature/load-jsonl`

Tick each box once its **Verify** command passes; don't move on until it does.

## 1. Backend: `prepare_session` (pure, read-only)
- [x] Backend: `prepare_session` (pure, read-only)

In `backend/main.py`: rebuild `messages` from records; group into `turns` (split on `role:"user"`,
pair `tool_calls` ↔ `role:"tool"` by `tool_call_id`, last non-empty assistant text = `answer`, empty →
`incomplete`). Return `messages` without the system message. Tolerate bad lines/unknown roles.

**Verify:** run `prepare_session` on `logs/371c7225-…jsonl` → 9 turns, steps+results present, no warnings.

## 2. Backend: two endpoints
- [x] Backend: two endpoints

`GET /api/sessions` (list, newest-first, skip empty) and `GET /api/sessions/{id}` (guard with
`is_safe_session_id`; 404 unsafe/unknown/empty).

**Verify:** TestClient → 200 for the real id (9 turns); 404 for `..%2F..%2Fetc%2Fpasswd` and `nope`.

## 3. Backend: tests
- [x] Backend: tests

Extend `backend/test_main.py`: real-log case; fixtures (header-only, incomplete, error, orphan tool
result, multiple calls, torn line); list sorting/filtering; 404s; continuation regression (seq continues,
no re-logging).

**Verify:** `cd backend && .venv/bin/python -m pytest -q` green.

## 4. Frontend: sidebar
- [ ] Frontend: sidebar

`App.tsx` + `App.css`: `[ + New chat ]`; items `local yyyy-mm-dd hh-mm-ss` then `id.slice(0,5)`,
newest-first, active highlight; disabled while `busy`; collapse under ~720px.

**Verify:** `cd frontend && pnpm build` clean.

## 5. Frontend: load + continue
- [ ] Frontend: load + continue

On mount load list; auto-open `?session=`. Select → set URL, `GET /api/sessions/{id}`, replace `turns`,
seed `history.current = messages` and `sessionIdRef.current = id`. Reuse `<TurnView>`; show
incomplete/error notes. "New chat" clears state + URL; refresh list after send.

**Verify:** open `/?session=371c7225-…` after reload → transcript restored; sending appends (seq continues)
to the same file.

## 6. Docs
- [ ] Docs

One line in `README.md` and `docs/architecture.md`: the two endpoints + read-only replay (no model call).

**Verify:** `grep -q "/api/sessions" README.md docs/architecture.md`.

## Done when
Sidebar lists non-empty sessions, timestamp-then-id, newest-first · selecting renders like a live session ·
opening calls no model / runs no bash · continuing appends to the same JSONL · `pytest` and `pnpm build` green.
