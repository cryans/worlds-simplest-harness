---
title: "plans/feature-event-loop-cleanup-retro.md"
branch: "feature/event-loop-cleanup"
feature: "event-loop-cleanup"
status: "complete"
references:
  - "plans/feature-event-loop-cleanup-requirements.md"
  - "plans/feature-event-loop-cleanup-design.md"
  - "plans/feature-event-loop-cleanup-plan.md"
---

# Event loop cleanup — retro

## Evidence (measured, not remembered)

| Measure | Before | After |
|---|---|---|
| Tests | 36 | **42** (green) |
| `agent_loop` yield type | `sse(...)` string frames | `SseEvent` models (`AsyncGenerator[SseEvent, None]`) |
| `sse()` signature | `sse(event: str, data: dict)` + `{"type": ...}` injection | `sse(event: SseEvent) -> str` |
| Wire contract | written twice (loop strings + `models.SseEvent`) | one source: the loop yields the union |
| Event names / payloads | `session`/`status`/`tool_call`/`tool_result`/`answer`/`error` | **unchanged** (semantically; `"type"` field order + whitespace differ) |
| UI | renders | renders (manual smoke: 3 prompts incl. tool calls + resume) |
| `api-types.ts` | — | **no diff** (`pnpm run check:api` clean) |

## What went well

1. **The rename saved us.** `session-domain` → `event-loop-cleanup` was the correct call. The DDD
   framing (`Session`/`Turn`/`TurnState`) was a wrong steer; what actually needed changing was the
   loop, nothing more. The requirements were re-scoped to match the real work.
2. **The north-star reference earned its keep.** Capturing the full re-typed `agent_loop` in
   `feature-event-loop-cleanup-northstar.md` before touching code made step 2 a mechanical copy, not
   a re-derivation. The `"type` is a required literal" finding was caught *before* the loop was
   written, so no `SessionEvent(session_id=...)` runtime failure ever appeared.
3. **The human UI gate was the right trade.** We deliberately did *not* add UI automation, and instead
   asked the user to smoke-test. That's the one check that actually proves the client still renders
   after the `"type"` reorder — and it passed on the tool-call path, the branch at risk.
4. **`check:api` proved the contract is unchanged.** `SseEvent` was already the wire contract, so the
   regenerated `api-types.ts` came back byte-identical — evidence the cleanup didn't drift the schema.

## What didn't go well

1. **The plan's test-count arithmetic was wrong on arrival.** It forecast "37 passed" (36 + 1 new
   test), but the parametrized `sse` test adds **6** cases → 42. Caught by running, not by the plan —
   the same class of error `model-failure-handling` already flagged. The lesson hasn't fully stuck.
2. **The "byte-for-byte identical" claim drifted.** Early narration said the wire was unchanged; a
   runtime check then showed `model_dump_json()` reorders fields (`"type"` first) and drops the
   `": "`/`", "` spacing. Harmless for `JSON.parse`, but the honest claim is "semantically identical,
   bytes differ" — and it was discovered by inspection, not a written-down check.
3. **The mermaid diagram churned.** Three iterations: a reserved-word collision (`participant Loop`
   vs `loop`), then a `rect` neither of us liked, then the swimlane. Fine as a design exercise, but it
   cost a round each — a check "is `loop`/`alt`/`rect`/`end` a reserved token here?" would have saved
   the first two.

## Learned

- **When one shape is written twice, the fix is "make the code produce the schema", not "add a third
  place".** The loop already had a `SseEvent` union it never used; the cleanup was to *use* it, not to
  build a domain model around it.
- **`type` as a required literal is a foot-gun.** Every event must be built with `type=`. If we ever
  want `SessionEvent(session_id=...)` to just work, that's a separate "defaulted literal" change to
  `models.py` — out of scope here, but worth remembering.
- **A human smoke test is not "lesser" than automation; it's the only test that exercises the actual
  consumer.** Knowing when a check is inherently manual is itself a skill.

## Decision archaeology

| Decision | Consequence | Would have been caught by |
|---|---|---|
| Rename branch `session-domain` → `event-loop-cleanup` | name matches the work; zero drift from main so rename was free | — (deliberate) |
| Scope = typed yields + one encoder; no `Session`/`Turn`/`TurnState` | small diff; no speculative domain model | an honest read of "what actually needs to change" |
| North-star doc as the implementation target | step 2 became a copy, catching `type`-required early | — (deliberate) |
| Manual UI smoke instead of UI automation | cheaper; tested the real consumer; passed on tool-call path | — (deliberate) |
| Keep `check:api` as the schema contract gate | proved no drift without adding a test | — (deliberate) |

## Review (implementer)

- **Well:** the pre-renamed branches of thinking (DDD vs loop) got reconciled into a small, honest
  feature; the north-star doc made implementation near-mechanical; the human gate was the right call.
- **Didn't:** I asserted "unchanged wire" too soon and got the test count wrong — two places where a
  quick run, rather than a claim, was the answer.
- **Learned:** measure before narrating. The two surprises (field reorder, 42≠37) were both a grep or
  `pytest` away.

## Actions

- None outstanding for this feature. Next per `plans/next-steps.md`: `sample-project-rework`.
