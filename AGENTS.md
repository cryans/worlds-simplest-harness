# AGENTS

## Commands

- Backend tests: `cd backend && uv run pytest -q`
- Dump the OpenAPI schema: `cd backend && uv run python dump_openapi.py /tmp/schema.json`
- Frontend build: `cd frontend && pnpm build`
- API contract check (regenerates types, fails on diff): `cd frontend && pnpm run check:api`

## SDLC

Requirements → design → plan → retro artifacts live in `plans/`.
