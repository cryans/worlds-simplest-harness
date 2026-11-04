---
branch: "model-failure-handling"
references:
  - "plans/feature-model-failure-handling-requirements.md"
---

# Model failure handling — implementation plan

Branch: `model-failure-handling`. Requirements: `feature-model-failure-handling-requirements.md`.

Tick each box only once its **Verify** passes; don't start the next step until it does.

> **Sandbox note:** `~/.cache/uv` is read-only in this harness, so plain `uv run` fails to lock its
> cache. Prefix `UV_CACHE_DIR=/tmp/uv-cache-wsh` (or export it) for every `uv run` in this plan.

## 1. Baseline
- [x] `git status --porcelain` clean except the requirements + plan docs; branch `feature/model-failure-handling`.
- [x] `cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run pytest -q` → **29 passed** (1 starlette DeprecationWarning). Record 29.

**Verify:** 29 passed. This is the "before" number.

## 2. Config — `wsh/config.py`
- [x] Add `MODEL_MAX_RETRIES = int(os.environ.get("MODEL_MAX_RETRIES", "2"))` next to `MAX_STEPS`/`BASH_TIMEOUT`.
- [x] Do **not** add a backoff knob here — backoff is a module constant in `wsh/agent/loop.py` (step 4).

**Verify:** `uv run pytest -q` → 29 passed. `uv run python -c "import wsh.config as c; print(c.MODEL_MAX_RETRIES)"` → `2`.

## 3. Session-scoped `step` — `wsh/session/log.py` + `wsh/agent/loop.py`
- [x] `wsh/session/log.py`: in `_resume()` also compute `self._step = max(rec.get("step", 0) for rec in records) + 1` (0 → starts at 1). Add `next_step(self) -> int` returning `self._step` then incrementing. `write_request`/`write_response`/`write_error` signatures stay unchanged (they still take a `step` argument).
- [x] `wsh/agent/loop.py`: change `for step in range(1, MAX_STEPS + 1):` to `for _ in range(MAX_STEPS):` with `step = log.next_step()` at the top of each iteration (before `write_request`). The per-turn `MAX_STEPS` bound and the log's session-scoped `step` are now two separate counters.
- [x] `backend/tests/test_session_log.py`: add `test_next_step_resumes_across_reopen` — write two request records (`step` 1, 2), reopen `SessionLog` on the same path, assert `next_step() == 3`.

**Verify:** `uv run pytest -q` → **30 passed**. Existing `write_request(..., step, ...)` tests are untouched (the log still accepts an explicit `step`; only the loop assigns it).

## 4. Retry + typed error messages — `wsh/agent/loop.py` (`wsh/agent/client.py` unchanged)
- [x] `wsh/agent/loop.py`: add `RETRY_BACKOFF_S = 1.0` and two pure helpers — `_retryable(exc) -> bool` and `_error_message(exc) -> str`:
  - `_retryable`: `httpx.HTTPStatusError` with `status_code == 503` → True; `httpx.DecodingError`/`httpx.TooManyRedirects` → False; any other `httpx.RequestError` (connect/timeout/read/write/protocol) → True; everything else → False.
  - `_error_message`: always includes `type(exc).__name__`; HTTPStatusError → `"Model error (<Name>): <status> <body>"`, otherwise `"Could not reach the model (<Name>): <str(exc) or 'no detail'>"` — so it is never empty.
- [x] Replace the `try/except` block in the loop with a bounded retry loop: catch an exception, if `_retryable(exc)` and `attempts < MODEL_MAX_RETRIES` then `attempts += 1`, `yield sse("status", {"text": f"retrying ({attempts}/{MODEL_MAX_RETRIES})…"})`, `await asyncio.sleep(RETRY_BACKOFF_S)`, and retry; otherwise `message = _error_message(exc)`, `log.write_error(message, step)`, `yield sse("error", ...)`, `return`. One `write_request` per round-trip (already written before the first attempt); retries emit no extra request/error lines.
- [x] `wsh/agent/client.py`: **no change** — it already raises the `httpx` exceptions the loop classifies.
- [x] `backend/tests/test_agent.py` (new): `asyncio.run(...)` + `monkeypatch` `wsh.agent.loop.call_model` (and `RETRY_BACKOFF_S` to 0). One test each: (a) 503-then-success → `answer` + a `retrying` status, one request + one response in the log; (b) `ConnectError`-then-success → `answer`; (c) always-503 → `error` whose message contains `HTTPStatusError` and is non-empty; (d) `ConnectTimeout("")` (empty str) → `error` containing `ConnectTimeout`; (e) 401 → `error` and the fake called exactly once (no retry).

**Verify:** `uv run pytest -q` → **35 passed**. (No new dev dep: async tests run through `asyncio.run`.)

## 5. Errors attach to their turn — `wsh/session/replay.py`
- [x] `wsh/session/replay.py`: replace `errors_by_step: dict[int, str]` (keyed by `step`, attached to `turns[-1]` via `max`) with turn-boundary tracking — increment a `turn_index` each time a `request.delta` carries a `role == "user"` message; on an `error` record store `errors_by_turn[turn_index] = message`; after grouping, attach `turns[i].error = errors_by_turn.get(i)` (not just the last turn).
- [x] `backend/tests/test_replay.py`: add `test_error_attaches_to_correct_turn` — turn 1 (`user "hi"` → `error "boom"`), turn 2 (`user "hi2"` → `response`): assert `turns[0].error == "boom"` and `turns[1].error is None`. Keep the existing single-turn error test passing.

**Verify:** `uv run pytest -q` → **36 passed**.

## 6. Docs
- [x] `README.md`: add `MODEL_MAX_RETRIES` (`2`) to the config table.

**Verify:** `grep -q MODEL_MAX_RETRIES README.md`; `uv run pytest -q` → 36 passed; `git status --porcelain` shows the intended edits.

## Notes from implementation (deltas from the plan as written)

- **Step 4 wrote 5 tests, not 4.** The plan listed five cases (a)–(e) but its
  "Verify"/"Done when" arithmetic said "+4 retry". Total is 36 (29 → +1 step,
  +5 retry, +1 attribution).
- **The "never empty" test uses `ConnectError("")`, not `ConnectTimeout("")`.**
  httpx's `TimeoutException.__str__` returns the class name when the message is
  empty, so `ConnectTimeout("")` has non-empty `str()`; `ConnectError("")` is the
  one whose `str(e) == ""`. That is what actually exercises the `'no detail'`
  fallback in `_error_message`.
- **`analyze_trajectories.py` and `plans/.feature-model-failure-handling-plan.md.swp`
  are left untouched** — both are the author's, not part of this feature.

## Done when
`uv run pytest` green with **36 tests** (29 → +1 step, +5 retry, +1 attribution) · `MODEL_MAX_RETRIES` in config + README · retry on 503/transport errors with a live `retrying` status · error messages always carry `type(e).__name__` and are never empty · `step` is a session-scoped, monotonic round-trip sequence resumed from `max(step)+1` · replay attaches each error to its own turn · `git status --porcelain` shows only the intended changes.
