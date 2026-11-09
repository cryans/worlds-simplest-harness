---
status: "active"
---

# Next steps

A working list of what to pick up next, kept deliberately short. Done items stay as
one-liners; active items get one "why". The full backlog lives elsewhere.

## Order

1. `sample-project-rework`
2. `harness-guardrails`
3. `document-sdlc`
4. `mermaid-validation`

## Done

- `isolate-test-fixtures`
- `typed-session-contract`
- `backend-refactor`
- `model-failure-handling`
- `event-loop-cleanup`

## Active

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
