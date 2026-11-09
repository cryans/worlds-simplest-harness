---
title: "plans/backlog-response-streaming-requirements.md"
feature: "response-streaming"
status: "proposed"
references:
  - "plans/backlog.md"
  - "plans/bug-tool-call-failures-swallowed-recovery.md"
  - "plans/backlog-agent-run-visibility-requirements.md"
  - "plans/backlog-token-usage-and-cost-requirements.md"
---

# Stream the model response — requirements

**Goal.** Stream the model's response instead of making a single non-streaming call, so
tokens arrive continuously and sessions never *appear* to hang on a slow model.

**Why now.** `call_model` uses `client.post(...)` with no `stream` and a fixed read timeout
(previously a hardcoded 60s; now `MODEL_TIMEOUT`, default 120s). A reasoner-style model
(e.g. one emitting `reasoning_content`) can exceed that on a single completion, raising
`ReadTimeout` and showing "Could not reach the model (ReadTimeout)…". Raising the timeout is
a stopgap; streaming is the real fix.

## Requirements

1. **Stream the completion.** The client must issue a streaming request and yield tokens as
   they arrive rather than blocking until the full response.
2. **No dead air.** As tokens stream, the UI shows progress (and forms the basis of the
   live token/cost bar in `live-token-usage-and-cost`).
3. **Read-deadline relief.** Streaming must reset the read deadline between chunks so a slow
   model doesn't trip the read timeout merely for being slow.
4. **Preserve tool-calling.** The agent loop must still assemble the assistant `message`,
   `tool_calls`, `finish_reason`, and `usage` from the stream and feed tool calls through the
   loop exactly as it does today.

## Gaps to close (not yet present)

- `call_model` in `wsh/agent/client.py` is non-streaming; needs `stream=True` plus async
  line/byte iteration (`aiter_lines()` or SSE parsing over the raw body).
- The agent loop consumes a whole response dict (`data["choices"][0]["message"]`,
  `finish_reason`, `usage`); it must build these incrementally from streamed deltas.
- The frontend has no "token delta" event type; a new SSE event (or reframing) is needed to
  carry `delta.content` and running `usage`.
- Tool-call turns: stream the prose/reasoning first, then emit the finished `tool_calls`
  block when the model completes them.

## Related

- `live-token-usage-and-cost` — streamed `usage` feeds the metrics bar.
- `agent-run-visibility` — streaming removes the main source of "is it stuck?" dead air.
