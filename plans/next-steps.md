---
status: "active"
---

# Next steps

A working list of what to pick up next, kept deliberately short. Done items stay as
one-liners; active items get one "why". The full backlog lives elsewhere.

## Order

1. `true-sandbox`
2. `sample-project-rework`
3. `harness-guardrails`
4. `document-sdlc`
5. `mermaid-validation`

## Done

- `sample-project-smoke-test`
- `isolate-test-fixtures`
- `typed-session-contract`
- `backend-refactor`
- `model-failure-handling`
- `event-loop-cleanup`

## Active

### true-sandbox
- Plugin-boundary smoke sandbox: smoke code in its own modules; main loop untouched; `bash` under `bwrap`.
- Why: smoke mode is currently only a cwd change, and it must not pollute the event loop.

### sample-project-rework
- Normal mode still uses repo-root `sample-project/`; the default sandbox is not env-configurable.
- Why: smoke mode is isolated, but ordinary runs remain coupled to the repo root.

### harness-guardrails
- ruff (size/complexity) + mypy + pre-commit/CI; no server-starting tool calls.
- Cap tool output fed to the model (`MAX_TOOL_OUTPUT_CHARS`); truncate stdout/stderr with a "refine your query" nudge.
- Why: guardrails belong in the harness, not in memory.

### document-sdlc — held until `harness-guardrails`
- One page: phases + artifacts + gates.

### mermaid-validation — anytime
- CI-render every mermaid block; fail on parse error.
