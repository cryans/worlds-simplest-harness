---
title: "plans/feature-event-loop-cleanup-requirements.md"
branch: "feature/event-loop-cleanup"
feature: "event-loop-cleanup"
status: "proposed"
references:
  - "plans/next-steps.md"
  - "plans/feature-model-failure-handling-retro.md"
  - "plans/feature-typed-session-contract-design.md"
---

# Event loop cleanup — requirements

**Goal.** Clean up the event loop: `agent_loop` yields typed `SseEvent` models (not
pre-encoded strings), and one encoder turns a model into an SSE frame. No domain
objects, no new states — just collapse the two hand-written descriptions of the loop
into one.

**Why now.** The loop's shape is good and stays. What's wrong is that the same shape
is described twice, by hand:

1. `agent_loop` yields pre-encoded SSE strings (`loop.py`), even though the `SseEvent`
   union already exists in `models.py`. The models are reflected into OpenAPI by a
   `custom_openapi` hook, but the loop never produces them.
2. `sse()` has inverted responsibilities: the loop decides `event:`/`data:` framing
   *and* injects `"type"` into the payload (`sse.py`), instead of one encoder turning
   a model into a frame.

Collapsing those two descriptions into one is the whole feature.

## Requirements

1. **The loop yields typed `SseEvent` models.** `agent_loop` is an
   `AsyncGenerator[SseEvent, None]` that yields model instances
   (`SessionEvent`, `StatusEvent`, `ToolCallEvent`, `ToolResultEvent`,
   `AnswerEvent`, `ErrorEvent`), never `sse(...)` strings. Boundary encoding is a
   separate concern.

2. **Encoding is one function at the boundary.** `sse(event: SseEvent) -> str`
   takes a model and returns the `event:`/`data:` frame. The event *name* and the
   `"type"` field in the payload both derive from the model's discriminator —
   one code path, no loop-side `"type"` injection. The chat route still streams the
   same event names + payloads the browser renders today.

3. **The union describes the loop's existing phases.** The models carry no states
   beyond what the loop already emits: `session` (handshake) → `status` (retry /
   step progress) → `tool_call` / `tool_result` → `answer` (tool-call-free finish)
   or `error` (failure). "The model made tool calls" is the loop's natural
   `tool_calls` branch, not a separate state object.

4. **`ToolCallEvent` / `ToolResultEvent` stay thin.** They continue to pair name →
   args/result exactly as the loop produces them today. No new `seq`/`id` fields
   are added unless the log needs them.

5. **Terminal events stay distinct.** `answer` and `error` remain separate literal
   types; an exhausted-retry or transport runtime failure is an `error` event, a
   tool-call-free finish (or a reachable step cap) is an `answer` event. This mirrors
   the current loop's semantics, not a unification.

6. **`SessionLog` remains the only persistent object.** The WAL (`request` /
   `response` / `error` / `session` records, each with `seq`/`step`/`ts`) is
   unchanged.

7. **Replay keeps deriving state.** `prepare_session` continues to rebuild
   `message`s / `turn`s / `warnings` from the record stream. The orphan-tool-result
   and unanswered-tool-call repairs stay exactly where they are today.

## Out of scope

- `TurnState` enum, `Turn`/`Session` domain entities, `turn_started` / `turn_index`.
  These were placeholders; the loop's shape is the real contract, and no current
  requirement needs them. (A state machine may inform the cleanup — see
  `plans/feature-event-loop-cleanup-design.md` — but it is a design note, not a
  deliverable.)
- New WAL record types / migrating existing `logs/*.jsonl`.
- Streaming model tokens (unchanged).
- `harness-guardrails` (ruff/mypy/pre-commit), `sample-project-rework`.

## Acceptance criteria

- `agent_loop` yields `SseEvent` instances, and `sse(model)` encodes them; the chat
  route's stream carries the same event names + payloads as before.
- `model-failure-handling` behaviors hold: 503/transport retry → eventual `answer`;
  exhausted retries and 4xx → `error` whose `message` names the exception type and
  is never empty; `step`/`seq` remain monotonic in the log.
- `prepare_session` behavior is unchanged (orphan tool results dropped with a
  warning, unanswered tool calls repaired, errors attached to the correct turn).
- `uv run pytest -q` green; `pnpm run check:api` regenerates `api-types.ts` with no
  contract break beyond the intentional typing change (and its diff is committed);
  `pnpm build` green.
