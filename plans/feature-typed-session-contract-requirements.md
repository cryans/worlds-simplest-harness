---
branch: "typed-session-contract"
status: "proposed"
references:
  - "plans/feature-load-jsonl-next-steps.md"
---

# Typed session contract — requirements

**Goal.** One source of truth for API shapes: Pydantic → OpenAPI → TypeScript. The UI stops
hand-mirroring the backend by memory.

## Requirements

1. `SessionTurn`, `SessionPayload`, `SessionMeta`, `SseEvent` (discriminated union on `type`) as
   Pydantic models; endpoints and `prepare_session` return them, not `dict`.
2. Generate `frontend/src/api-types.ts` from `/openapi.json` via `openapi-typescript`.
3. `App.tsx` imports those types; zero hand-written API types remain.
4. CI fails when the generated file is stale (`git diff --exit-code`).

## Out of scope
Behaviour/JSON changes, state-machine refactor, `ruff`/`mypy`/pre-commit → `harness-guardrails`.
