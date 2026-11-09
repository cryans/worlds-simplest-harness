---
title: "plans/backlog.md"
status: "active"
references:
  - "plans/next-steps.md"
  - "plans/backlog-agent-run-visibility-requirements.md"
  - "plans/backlog-response-streaming-requirements.md"
  - "plans/backlog-token-usage-and-cost-requirements.md"
  - "plans/backlog-nameable-sessions-requirements.md"
---

# Backlog

Ideas that are wanted but not yet scheduled for active work. `next-steps.md` is
the deliberately-short "what to pick up next" list; this is the longer shelf it
points at. Items here are candidates, not commitments — order is not priority
until something is promoted into `next-steps.md`.

## Wish list

### agent-run-visibility *(is it stuck or running?)*
- Surface the `status` events the backend already emits (the frontend drops them today).
- Live "where am I" indicator: phase + elapsed time + step number, replacing the bare "Working…".
- Mark an in-flight `tool_call` as "executing…" until its `tool_result` returns.
- Why: during a run it is currently impossible to tell "waiting on model" from "retrying" from "running bash" from "hung".

### response-streaming *(no hanging sessions)*
- Stream the model response instead of the single non-streaming call, so tokens arrive
  continuously and a slow reasoner model doesn't trip `ReadTimeout` just for being slow.
- Why: the fixed 60s read timeout on a non-streaming call is the cause of "hanging" sessions;
  `MODEL_TIMEOUT` is a stopgap, streaming is the real fix. Also feeds the token/cost bar.

### live-token-usage-and-cost
- Persistent, non-intrusive metrics bar (footer/input area), updating each turn / stream chunk.
- Show input vs. output tokens, prefix-cache hit-vs-miss, cumulative session cost in USD, and a
  context-window "how full" indicator.
- Why: the usage data is already captured in the JSONL; the developer wants it live to watch
  consumption and avoid budget spikes. Needs a price table + per-model context size (not yet present).

### nameable-sessions
- Name/title sessions instead of showing only a date + truncated UUID in the sidebar.
- Needs a durable `name` on the session (append-only `rename` event or header field),
  a rename endpoint, and inline editing in the UI.
- Why: many debugging runs are indistinguishable by date alone.

## Waiting for something

### document-sdlc
- Held until `harness-guardrails` lands (see `next-steps.md`).

### mermaid-validation
- CI-render every mermaid block; fail on parse error. "Anytime", per `next-steps.md`.
