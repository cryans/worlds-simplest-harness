---
branch: "model-failure-handling"
feature: "model-failure-handling"
status: "complete"
references:
  - "plans/feature-model-failure-handling-requirements.md"
  - "plans/feature-model-failure-handling-plan.md"
---

# Model failure handling — retro

## Evidence (measured, not remembered)

| Measure | Before | After |
|---|---|---|
| Tests | 29 | **36** (green) |
| Retry | none — any failure killed the turn | 503 + transport errors, `MODEL_MAX_RETRIES` (default 2) |
| Error message | `f"…{e}"` → empty when `str(e) == ""`, no type name | always `type(e).__name__`, never empty |
| `step` | per-turn counter, resets to 1 | session-scoped round-trip sequence, resumed from `max(step)+1` |
| Error replay | keyed by `step` → collision + pinned to last turn | keyed by turn boundary → correct turn |
| `agent/client.py` | — | **unchanged** |

## What went well

1. **The requirements phase earned its keep.** The user's loop caught four real mis-frames before
   any code: "drop `step`" (wrong — keep it), "`step` = line number" (wrong — it's a round-trip
   counter, distinct from `seq`), "global `step`" (wrong word — session-scoped), and "retry lives in
   `call_model`" (wrong — it lives in the loop so it can `yield` a live status). Each correction
   changed the code that got written.
2. **Retry in the loop, not the client.** Putting the bounded retry loop in `agent/loop.py` (and
   leaving `client.py` as a single attempt) made the live `retrying (n/N)…` status a one-line
   `yield`, and kept the client testable and untouched.
3. **No new dev dependency.** The async loop is tested with `asyncio.run` + `monkeypatch` on
   `wsh.agent.loop.call_model`, so `pytest-asyncio` never entered the picture.
4. **The per-step Verify discipline held.** 29 → 30 → 35 → 36, each step provable in seconds.

## What didn't go well

1. **The `step` semantics took four rounds to settle.** I mislabeled it "global" (a real code
   smell — the counter is an instance attribute resumed from the file, not process state), then
   proposed deleting the field, then said "line number", before the human pinned it: *session-scoped
   round-trip sequence*. That is time that should have been one careful read of `log.py` + `loop.py`.
2. **The plan's arithmetic and one test were wrong on arrival.** It listed five retry cases but said
   "+4 tests"; and its empty-`str` case named `ConnectTimeout("")`, whose `__str__` falls back to the
   class name in httpx — `ConnectError("")` is the exception that actually stringifies to nothing.
   Both were caught by running, not by the plan.
3. **Scope crept.** "Retry + non-empty errors" became "retry + typed errors + session-scoped `step` +
   replay attribution". Each was a real, harness-reachable bug the human wanted fixed now, but the
   feature outgrew its one-line backlog entry.

## Learned

- **"Global" is a red flag in code.** The step counter is *session-scoped*: `self._step` on
  `SessionLog`, derived from the file on reopen (`max(step)+1`), exactly like `seq`. Say that, not
  "global".
- **`seq` and `step` are two different numbers.** `seq` is the per-line WAL number; `step` is the
  round-trip number. Conflating them ("step = line number") was the source of most of the confusion.
- **The replay bug was two bugs.** `errors_by_step[step]` overwrote across turns (collision) *and*
  `errors_by_step[max(...)] → turns[-1]` pinned to the wrong turn (mis-attachment). Keying by turn
  boundary fixes both; making `step` monotonic would have fixed only the first.
- **Retry is safe because the POST is idempotent.** Tools run only after a successful response, so
  re-sending the same request has no side effects — that's the whole justification for "retry".

## Decision archaeology

| Decision | Consequence | Would have been caught by |
|---|---|---|
| Retry scope = 503 + transport only | 429/502/504 fail fast; matches the backlog note; minimal | — (deliberate) |
| Retry loop in `loop.py`, `client.py` untouched | live `retrying` status trivial; client stays single-attempt | — (deliberate) |
| `step` stays, becomes session-scoped (not removed, not `seq`) | no migration; `max(step)+1` resume; distinct from `seq` | a careful read of `log.py`/`loop.py` |
| Key errors by turn boundary, not `step`/`seq` | fixes collision + mis-attachment; leaves a leading-assistant edge deferred to `session-domain` | a multi-turn failure fixture |
| `asyncio.run` + monkeypatch, no `pytest-asyncio` | no new dep; async loop testable today | — (deliberate) |
| No migration of existing `logs/*.jsonl` | old files replay correctly anyway (attribution no longer reads `step`) | a replay test against the 20-turn `098ca653` log |

## Review (implementer)

- **Well:** the human loop caught what my first-draft requirements kept getting wrong — every
  correction was a genuine design bug, not style. Retry-in-loop and turn-boundary attribution were
  the right calls.
- **Didn't:** I reached for "global" and "drop the field" instead of reading `log.py`/`loop.py`
  carefully first; the `step` semantics should have been settled in one pass, not four.
- **Learned:** for a WAL, every record — including an `error` — is a first-class event with its own
  `seq`; "failure is a step". And "session-scoped, resumed from the file" is the vocabulary to use,
  never "global".

## Review (human)

- Spent most of the session designing the agent loop, not this feature; from that vantage it went
  well.
- Concern: the old `logs/*.jsonl` still carry per-turn `step` — the exact invariant violation
  `analyze_trajectories.py` flags. Tempted to archive the logs and fix them up.
- Manual smoke tests looked good.
- Energy: the ~3-day wall was reached — winding down.

## Actions

1. **`session-domain`** (next) — turn state machine; the deferred leading-assistant attribution edge
   (logged in `plans/next-steps.md`).
2. **`analyze_trajectories.py`** — the author's scratch script that surfaced the `step` collision;
   delete once its job is done (not part of this feature).
3. `model-failure-handling` is done — move it to "Done" in `plans/next-steps.md` at commit time.
