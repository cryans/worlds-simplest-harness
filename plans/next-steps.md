---
status: "active"
---

# Next steps

A working list of what to pick up next, kept deliberately short. Done items stay as
one-liners; active items get one "why". The full backlog lives elsewhere.

## Order

1. `model-failure-handling`
2. `session-domain`
3. `sample-project-rework`
4. `harness-guardrails`
5. `document-sdlc`
6. `mermaid-validation`

## Done

- `isolate-test-fixtures`
- `typed-session-contract`
- `backend-refactor`

## Active

### model-failure-handling — next
- Retry on 503 / connection errors; error messages include `type(e).__name__` (never empty).
- Why: DeepSeek failures kill turns with no recovery.

### session-domain
- Turn state machine: `idle → awaiting_user → tool_calls_pending → tool_results → answered | incomplete | errored`.
- Per-turn error attachment; settle `step` semantics (errors keyed by `step` collide across turns — see `4a3bd8de`).
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
