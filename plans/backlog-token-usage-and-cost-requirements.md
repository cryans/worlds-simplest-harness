---
title: "plans/backlog-token-usage-and-cost-requirements.md"
feature: "live-token-usage-and-cost"
status: "proposed"
references:
  - "plans/backlog.md"
  - "plans/next-steps.md"
  - "plans/backlog-response-streaming-requirements.md"
  - "plans/backlog-agent-run-visibility-requirements.md"
---

# Live token usage and cost — requirements

**Goal.** Give the developer real-time visibility into token usage and financial cost
while running iterative coding tasks, so they can monitor consumption, track prefix-cache
efficiency, and avoid budget spikes during long debugging sessions.

**Why now.** The usage data already exists — every `response` record in the session JSONL
carries `usage` (`prompt_tokens`, `completion_tokens`, `total_tokens`, plus
`prompt_tokens_details.cached_tokens` and `prompt_cache_hit/miss_tokens`). This feature is
mostly *surfacing* already-captured data, not adding capture.

## Requirements

### A. Live status bar / footer visibility
1. **Persistent placement.** A subtle, non-intrusive metrics bar must remain visible
   (anchored to the footer or input area), not hidden behind a hover or a separate page.
2. **Real-time updates.** The display updates immediately on completion of each agent turn
   (and, with response streaming, per chunk).

### B. Core metrics displayed
3. **Token breakdown.** Separate input (prompt) tokens from output (completion) tokens for
   the current session.
4. **Cache efficiency.** For prefix-caching providers (e.g. DeepSeek), show the proportion
   of prompt tokens served from cache vs. misses, highlighting the cost savings.
5. **Running session cost.** A cumulative total in USD for the active session, computed
   dynamically across all turns.
6. **Context window budget.** A visual indicator/percentage of how much of the model's total
   context capacity is occupied by the current conversation history.

## Gaps to close (not yet present)

- **Live stream has no `usage`.** The live SSE stream does not carry `usage`; only the JSONL
  `response` records do. Decide: add `usage` to a live event, or derive from the session log.
- **No price table.** USD cost requires `$ per 1M tokens` for input (cached vs. miss) and
  output, per model. This must be configurable in the harness and kept current.
- **No context-window size.** Computing the "% full" indicator needs a per-model maximum
  context size that the harness doesn't currently know.

## Related

- `response-streaming` — streaming feeds incremental `usage` to the same bar.
- `agent-run-visibility` — the metrics bar replaces the bare "Working…" with live state.
