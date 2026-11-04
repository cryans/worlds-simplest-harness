---
branch: "model-failure-handling"
feature: "model-failure-handling"
status: "proposed"
references:
  - "plans/next-steps.md"
  - "plans/feature-backend-refactor-retro.md"
---

# Model failure handling — requirements

**Goal.** A transient DeepSeek failure stops killing the turn: retry on 503 and
connection errors, and every error message names the exception type (never empty).

**Why now.** `call_model` makes one non-streaming POST and any failure aborts the
turn (loop.py:42-53). DeepSeek returns 503s under load; connect/read timeouts are
transient too — but today one hiccup turns "asking the model…" into an error with
no recovery. And `f"Could not reach the model: {e}"` is empty when `str(e) == ""`,
while `f"Model error: {status} {text}"` omits the exception type, so failures are
hard to diagnose from a log line.

## Requirements

1. **`step` is session-scoped and monotonic.** `step` numbers model round-trips
   within one session and never resets between turns — Turn 1 is `1..n₁`, Turn 2
   is `n₁+1..n₁+n₂`. It is persisted in the log and resumed on reopen
   (`max(step)+1`) exactly like `seq`: a property of the `SessionLog`, not a
   process-global. It stays a distinct field from `seq` (the per-line WAL
   number).
2. **Retry transient failures.** The agent loop retries the model call on HTTP
   503 and on transport-level errors (`httpx.RequestError` — connect/timeout/
   read/write/protocol), bounded, with a short backoff. Non-transient failures
   (4xx, other 5xx, `DecodingError`, `TooManyRedirects`) fail immediately.
3. **Retries are not new steps.** Each model round-trip is one write-ahead
   `request` line followed by exactly one terminal line — `response` on success,
   `error` when retries are exhausted. Retries are transport attempts inside that
   one round-trip (the delta is identical), so they emit no extra lines; the
   `error` line is a first-class WAL event with its own `seq`.
4. **Error messages name the type.** Every model-call error message (the SSE
   `error` event *and* `log.write_error`) includes `type(e).__name__` and is never
   empty, even when `str(e) == ""`.
5. **Bounded + configurable.** Max retry count via env var (`MODEL_MAX_RETRIES`,
   default 2) in `config.py`, matching the existing env pattern.
6. **Visible retries.** While a retry is pending, stream a `status` event
   ("retrying…") so the UI isn't silently stuck on "asking the model…".
7. **Errors attach to their turn.** Replay attributes each `error` record to the
   turn that produced it (tracked by the turn boundary in the record stream), not
   by a `step`. A failed round-trip's error appears on that turn only; later
   turns don't inherit an earlier turn's error.

## Out of scope

- 429/502/504 and other statuses — keep to the note: 503 + connection errors.
- Retrying tool (`bash`) failures — already reported as `tool_result` errors.
- Exponential backoff with jitter / circuit breaker.
- `session-domain` turn state machine (#2). The `step` semantics are settled here (requirement 1: `step` becomes a session-scoped, monotonic round-trip sequence), so `session-domain` no longer carries that piece.
- Migrating existing `logs/*.jsonl` to a monotonic `step` — new records resume from `max(step)+1`; old files replay correctly via requirement 7, so no one-time renumber pass is needed.
- Streaming the model's tokens (unchanged).

## Acceptance criteria

- A 503-then-success response yields the answer (retry works).
- A connection-error-then-success response yields the answer.
- Exhausted retries yield an `error` whose message is non-empty and contains the
  exception type name.
- In a multi-turn replay, an error from an earlier turn is shown on that turn and
  not on any later turn.
- `step` is a single monotonic sequence across the whole session — each turn's
  first step continues from the previous turn's last, never resetting to 1.
- A 4xx fails immediately with no retry.
- `uv run pytest -q` green.
