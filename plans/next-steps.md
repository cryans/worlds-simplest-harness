---
status: "active"
---

# Next steps

A working list of what to pick up next, kept deliberately short. Done items stay as
one-liners; active items get one "why". The full backlog lives elsewhere.

## Order

1. `session-domain`
2. `sample-project-rework`
3. `harness-guardrails`
4. `document-sdlc`
5. `mermaid-validation`

## Done

- `isolate-test-fixtures`
- `typed-session-contract`
- `backend-refactor`
- `model-failure-handling`

## Active

### session-domain
- Turn state machine: `idle → awaiting_user → tool_calls_pending → tool_results → answered | incomplete | errored`.
- Per-turn error attachment + `step` semantics landed in `model-failure-handling`. Remaining edge: `prepare_session` keys errors by turn boundary, so a leading assistant turn (no preceding `user` message) misaligns them, and an error before any user message is dropped — the harness never writes such a log, but the state machine should make attribution structural.
- Why: the dangling-tool-calls repair exists because tool-calling isn't a state.

### sample-project-rework
- Env-configurable sandbox path, outside the repo.
- Why: the sandbox is gitignored but coupled to the repo root; it pollutes and diverges.

### harness-guardrails
- ruff (size/complexity) + mypy + pre-commit/CI; no server-starting tool calls.
- Cap tool output fed to the model (`MAX_TOOL_OUTPUT_CHARS`); truncate stdout/stderr with a "refine your query" nudge.
- Why: guardrails belong in the harness, not in memory.

### document-sdlc — held until `harness-guardrails`
- One page: phases + artifacts + gates.

### mermaid-validation — anytime
- CI-render every mermaid block; fail on parse error.
