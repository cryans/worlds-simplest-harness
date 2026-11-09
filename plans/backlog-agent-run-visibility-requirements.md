---
title: "plans/backlog-agent-run-visibility-requirements.md"
feature: "agent-run-visibility"
status: "proposed"
references:
  - "plans/backlog.md"
  - "plans/bug-tool-call-failures-swallowed-recovery.md"
  - "plans/backlog-response-streaming-requirements.md"
  - "plans/backlog-token-usage-and-cost-requirements.md"
---

# Agent-run visibility ("is it stuck or running?") — requirements

**Goal.** Make it obvious, during a live run, whether the harness is waiting on the model,
retrying, executing a tool, or hung — replacing the single ambiguous "Working…" state.

**Why now.** The only live signal is the button flipping `Send → Working…`, where `Working…`
stays true for the whole loop with no intermediate feedback. The backend already emits
`status` events, but the frontend drops them.

## Requirements

1. **Surface existing `status` events.** The frontend must render `StatusEvent` (adding a
   `status` branch to the `switch(event.type)` in `App.tsx`); the "asking the model…" and
   "retrying (n/N)…" text already sent must be visible.
2. **Live "where am I" indicator.** Show phase (asking model / retrying / running tool / done),
   elapsed wall-clock time since the turn began, and the step/round-trip number. Replace the
   bare "Working…" label with e.g. `Working… 12s · step 3 · asking the model`.
3. **Tool execution is visibly in flight.** Between a `tool_call` and its `tool_result`, show
   the command as "executing…" (with elapsed time), distinct from completed/failed.

## Open questions

- Where does phase/step data come from — extend `StatusEvent`, add fields to `ToolCallEvent`,
  or infer client-side from the event stream?
- Does elapsed time live client-side (a ticker between events), or do events carry a server
  `ts`? (The live stream has no `ts` today; the JSONL does.)

## Related

- `response-streaming` — streaming removes the largest "dead air" this feature otherwise works around.
- `live-token-usage-and-cost` — the status line and metrics bar can share the footer placement.
