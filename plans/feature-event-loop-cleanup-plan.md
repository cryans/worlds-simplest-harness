---
title: "plans/feature-event-loop-cleanup-plan.md"
branch: "feature/event-loop-cleanup"
feature: "event-loop-cleanup"
status: "complete"
references:
  - "plans/feature-event-loop-cleanup-requirements.md"
  - "plans/feature-event-loop-cleanup-design.md"
  - "plans/feature-event-loop-cleanup-northstar.md"
---

# Event loop cleanup — implementation plan

Branch: `feature/event-loop-cleanup`. Requirements: `feature-event-loop-cleanup-requirements.md`.
Design: `feature-event-loop-cleanup-design.md`. North star (the full re-typed loop):
`feature-event-loop-cleanup-northstar.md`.

Tick each box only once its **Verify** passes; don't start the next step until it does.

> **Sandbox note:** `~/.cache/uv` is read-only in this harness, so plain `uv run` fails to lock its
> cache. Prefix `UV_CACHE_DIR=/tmp/uv-cache-wsh` for every `uv run` in this plan.

## 1. Baseline

- [x] `cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run pytest -q` → **36 passed** (the current
      count; recorded 2026-11-09). Record it below as the "before" number.
- [x] `git status --porcelain` shows only the `event-loop-cleanup` docs (requirements/design/plan/
      northstar + `next-steps.md`) plus the author's own untracked files (`analyze_trajectories.py`,
      `title-front-matter.py`, `docs/architecture-vision.md`). No `backend/src` or `frontend/src`
      edits yet.

**Verify:** 36 passed. Working tree shows no code edits. → here's the before number: **36**.

## 2. Make `agent_loop` yield models — `backend/src/wsh/agent/loop.py`

- [x] Copy the full re-typed `agent_loop` from `feature-event-loop-cleanup-northstar.md` into
      `agent/loop.py`. Every `yield sse("name", {...})` → `yield <Type>Event(type="name", ...)`.
- [x] All 9 loop yield sites become models: `session`(1), `status` "asking" (1), `status` "retrying"
      (1), `error` (1), `answer` no-tool (1), `tool_result` unknown-tool (1), `tool_call` (1),
      `tool_result` (1), `answer` max-steps (1).
- [x] Change the signature to `async def agent_loop(messages, log) -> AsyncGenerator[SseEvent, None]`
      and import the event models + `SseEvent` from `wsh.models`. Drop the now-unused `from wsh.sse
      import sse` import.
- [x] Keep `log.*` WAL writes, the retry loop, `_retryable`/`_error_message`, and tool-arg parsing
      **exactly where they are** — only the `yield`s change.
- [x] `backend/tests/test_agent.py`: update `_parse`/`_collect` helpers so they read model instances
      (`.model_dump()` or attribute access) instead of `event:`/`data:` string frames.

**Verify:** `uv run pytest -q` → **36 passed** (same count; the loop's behavior is unchanged, only the
yield type changed). No `sse(` remains in `agent/loop.py` (`grep -c "sse(" wsh/agent/loop.py` → 0).

## 3. One encoder — `backend/src/wsh/sse.py`

- [x] Rewrite `sse` to take a model and emit a frame:
  ```python
  def sse(event: SseEvent) -> str:
      return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"
  ```
  `event.type` gives the frame name; `model_dump_json()` already includes `"type"` (verified). No
  `{"type": ...}` injection.
- [x] Import `SseEvent` from `wsh.models` in `sse.py` (`SseEvent` is defined in `models.py`, and
      `sse.py` must not import `config`/`tools`/`agent`/`session`).

**Verify:** `uv run python -c "from wsh.models import SessionEvent; from wsh.sse import sse; print(sse(SessionEvent(type='session', session_id='x')))"` →
`event: session\ndata: {"type":"session","session_id":"x"}`.

## 4. Wire the route — `backend/src/wsh/api/routes.py`

- [x] In `chat()`, wrap the generator so each yielded model passes through `sse(model)`:
  `StreamingResponse((sse(e) async for e in agent_loop(messages, log)), media_type="text/event-stream")`.
- [x] The one non-loop `sse` call (lines 31-35: missing `API_KEY`) becomes
      `iter([sse(ErrorEvent(type="error", message="Set DEEPSEEK_API_KEY first."))])`.
- [x] Import `ErrorEvent` (and keep the `from wsh.sse import sse` import) in `routes.py`.

**Verify (automated):** `uv run pytest -q` → **36 passed**.

**Verify (human — the UI gate):** this is the step where we prove the client still renders after the
`type` reordering. Run it, don't infer it:

1. `cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run uvicorn wsh.api.app:app --reload` (or your
   usual run command).
2. `cd frontend && pnpm dev` and open the UI in the browser.
3. Send one prompt that **forces a tool call** (e.g. "run `ls` in the project" or "list the files").
   Watch for, in order: `session` → `status` → `tool_call`/`tool_result` (the tool-call swimlane in
   the UI) → and a final prose `answer`.
4. Send one prompt that needs **no tool** ("say hello") and confirm a plain `answer` renders.
5. Confirm an **error path** if convenient (e.g. temporarily unset the key) → the UI surfaces the
   `error` event text.

**Pass =** the event names/handling are unchanged and every event still renders. If the UI breaks
here, it's because of the `"type"` field reorder/whitespace — stop and surface it; do not "fix it
later".

Do **not** proceed to step 5 until this UI smoke passes.

## 5. Encoder test + contract check

- [x] Add one small `backend/tests/test_sse.py` — a single parametrized test asserting that
      `sse(model)` emits an `event: <type>` line and a `data:` line whose `json.loads` equals the
      model's serialized form (semantic equality, not bytes). This pins the *encoder contract* only;
      it does **not** stand in for the step-4 UI smoke.
- [x] `cd frontend && pnpm run check:api` → regenerates `src/api-types.ts` and `git diff --exit-code`.
      The `SseEvent` union is unchanged, so expect a **clean pass (no diff)**. If a diff appears,
      inspect and commit it deliberately — but it should not.

**Verify:** `uv run pytest -q` → **42 passed** (36 + 6 parametrized `sse` encodings). `pnpm run
check:api` → exit 0 (no diff). `cd frontend && pnpm build` → green.

## 6. Docs + retro

- [x] `plans/next-steps.md`: move `event-loop-cleanup` from Active to Done (and drop its "why" bullet).
- [x] Commit: the `event-loop-cleanup` docs + `backend/src` changes + `frontend` regenerated types
      (if any) + `next-steps.md`.
- [x] Write `plans/feature-event-loop-cleanup-retro.md` — measured before/after table (tests,
      `agent_loop` yield type, `sse` signature) + review, in the `model-failure-handling` retro shape.

**Verify:** `git status --porcelain` shows only intended edits; all checkboxes above ticked;
`feature-event-loop-cleanup-retro.md` exists.

---

## Notes from design (captured so they aren't re-derived in code)

- **`type` is a required literal.** Confirmed: `SessionEvent(session_id='abc')` raises
  `Field required [type=missing]`. Every event must be built with explicit `type=`. Making `type`
  defaulted is a separate `models.py` change, out of scope.
- **The discriminator round-trips.** `TypeAdapter(SseEvent).dump_python(e, mode='json')` preserves
  `"type"`; `validate_python` restores the subclass (verified).
- **`model_dump_json()` already emits `"type"`** (verified) — so the encoder only needs `event.type`
  for the frame name.
- **`sse.py` must not import `config`/`tools`/`agent`/`session`** — only `models` (the enforced
  boundary stays intact).

## Done when

`agent_loop` yields `SseEvent` models · `sse(model)` is the single encoder · chat route streams the
same event names + payloads with `"type"` · retry/error/prepare_session behavior unchanged ·
`uv run pytest -q` = **42 passed** · `pnpm run check:api` clean (no diff) · `pnpm build` green ·
`feature-event-loop-cleanup-retro.md` written · `next-steps.md` updated.
