---
branch: "backend-refactor"
feature: "backend-refactor"
status: "proposed"
references:
  - "plans/next-steps.md"
  - "plans/feature-typed-session-contract-retro.md"
---

# Backend refactor — requirements

**Goal.** Replace the 955-line `backend/main.py` with a small `wsh` package under
`backend/src/`, reproducible via `pyproject.toml`, and shrink the test suite to one test per
distinct behaviour. No user-visible behaviour change.

## Requirements

1. **Deps.** Add `backend/pyproject.toml` for package `wsh` (runtime + dev deps, pytest
   options). Delete `requirements.txt` and `requirements-dev.txt`. `uv run pytest` and
   `uv run python dump_openapi.py …` work on a clean checkout (no pre-existing `.venv`).
2. **Layout.** Code moves to `backend/src/wsh/`: `config.py`, `models.py`, `session/`
   (log, replay), `tools/`, `agent/loop.py`, `api/`. Keep `backend/main.py` as the obvious
   assembly entrypoint (<60 lines) that exposes `app`; `uvicorn main:app` still works.
3. **Model boundary.** `wsh/models.py` holds only Pydantic models (request, session, SSE)
   plus any OpenAPI glue needed. Importing it must not load `.env`, create directories, or
   import the LLM client/tools/agent. `dump_openapi.py` imports `wsh.api.app` — never `main`.
4. **Tests.** Re-home tests to mirror the new modules; aggressively prune overlaps; keep one
   test per distinct behaviour; drop duplicate fixtures/assertions. Suite green before and after.
5. **No behaviour change.** API paths, SSE events, env vars, and commands stay identical;
   the suite is the contract.

## Out of scope
`session-domain` (#4), `harness-guardrails` (#5), `justfile`, new features, any behaviour change.

## Acceptance criteria
- `uv run pytest` green before and after, with fewer tests.
- `uv run python dump_openapi.py /tmp/schema.json` succeeds.
- `pnpm run check:api` exits 0.
- `backend/requirements*.txt` gone; `main.py` < 60 lines, assembly only.
