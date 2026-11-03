---
branch: "backend-refactor"
references:
  - "plans/feature-backend-refactor-design.md"
  - "plans/feature-backend-refactor-requirements.md"
---

# Backend refactor — implementation plan

Branch: `backend-refactor`. Requirements: `feature-backend-refactor-requirements.md`.

Tick each box only once its **Verify** passes; don't start the next step until it does.

**How the split stays green.** Steps 3–7 move one concern out of `main.py` into a `wsh` module and
*re-import the moved names back into `main.py`* (`from wsh.config import …`). The old
`tests/test_main.py` keeps passing against `main.*`, so the suite is green after every move.
Step 8 re-homes the tests to `wsh.*`; step 9 deletes the re-imports, leaving `main.py` as assembly.

> **Sandbox note:** in this harness `~/.cache/uv` is read-only, so plain `uv run` fails to lock its
> cache. Prefix `UV_CACHE_DIR=/tmp/uv-cache-wsh` (or export it) for every `uv run` in this plan. The
> acceptance criteria themselves are unchanged.

## 1. Baseline
- [x] `git status --porcelain` clean except the two plan docs; branch `feature/backend-refactor`.
- [x] `cd backend && uv run pytest -q` → **32 passed** (1 starlette DeprecationWarning). Record 32.

**Verify:** 32 passed. This is the "before" number the "fewer tests" criterion compares against.

## 2. `pyproject.toml` + drop `requirements*.txt`
- [x] Add `backend/pyproject.toml` (design sketch), runtime deps: `fastapi==0.115.6`,
      `uvicorn[standard]==0.34.0`, `httpx==0.28.1`, `python-dotenv==1.0.1`, **`pydantic==2.14.1`**.
      `pydantic` is explicit because `models.py` imports it directly; the pin matches what
      `fastapi` already resolves, so nothing moves.
- [x] dev group `pytest==8.3.4`; `[tool.pytest.ini_options] testpaths = ["tests"]`; hatchling src
      build (`packages = ["src/wsh"]`); `requires-python = ">=3.12"`.
- [x] Add empty `backend/src/wsh/__init__.py` so the editable install has a package to build.
- [x] Delete `backend/requirements.txt` and `backend/requirements-dev.txt`.
- [x] `uv sync` (generates `uv.lock`; gitignored — deps are `==`-pinned in `pyproject.toml`).

**Verify:** `uv run pytest -q` → 32 passed (flat `main.py` still imported via `conftest.py`'s
`sys.path` insert). `uv run python dump_openapi.py /tmp/schema.json` writes the schema.
`ls backend/requirements*.txt` → nothing.

## 3. Foundation: `config.py`, `models.py`, `sse.py`
- [x] `config.py`: `load_dotenv()`, `API_KEY`/`BASE_URL`/`MODEL`/`MAX_STEPS`/`BASH_TIMEOUT`,
      `SAMPLE_PROJECT` (+`.mkdir`), `LOGS_DIR`, `SYSTEM_PROMPT`. The only side-effectful module.
- [x] `models.py`: `ChatRequest`, `ToolStep`, `SessionTurn`, `SessionMeta`, `SessionList`,
      `SessionPayload`, the six SSE event models + `SseEvent` union. **The boundary**: imports
      pydantic only — never config/tools/agent/session.
- [x] `sse.py`: `sse()` only. `now_iso` → `session/log.py` (step 4); `is_safe_session_id` →
      `api/routes.py` (step 7).
- [x] `main.py` re-imports these names.

**Verify:** `uv run pytest -q` → 32 passed.

## 4. Session: `log.py`, `replay.py`, `meta.py`
- [x] `log.py`: `SessionLog` + `now_iso()`; keep `logs_dir: Path = LOGS_DIR` (imports config —
      session's only config reference).
- [x] `replay.py`: `read_records`, `_parse_json_arg`, `_unanswered_tool_call_indexes`,
      `prepare_session`.
- [x] `meta.py`: `_parse_ts`, `_updated_at`, `_session_meta`.
- [x] `session/__init__.py` re-exports the public names; `main.py` re-imports them.

**Verify:** `uv run pytest -q` → 32 passed.

## 5. Tools: `registry.py`, `bash.py`, `manage_plan.py`
- [x] `registry.py`: `@tool`, `TOOLS`, `TOOL_REGISTRY`, `call_tool`.
- [x] `bash.py`: `run_bash` + `@tool bash` (uses `SAMPLE_PROJECT`, `BASH_TIMEOUT`).
- [x] `manage_plan.py`: `@tool manage_plan`.
- [x] `tools/__init__.py` imports the handlers so `@tool` registers them at import time;
      `main.py` re-imports.

**Verify:** `uv run pytest -q` → 32 passed.

## 6. Agent: `client.py`, `loop.py`
- [x] `client.py`: `call_model` (httpx; `API_KEY`/`BASE_URL`/`MODEL`/`TOOLS`).
- [x] `loop.py`: `agent_loop` (`MODEL`, `MAX_STEPS`, `sse()`). No retry — out of scope.
- [x] `main.py` re-imports.

**Verify:** `uv run pytest -q` → 32 passed.

## 7. API: `app.py`, `routes.py`
- [x] `app.py`: `app = FastAPI(...)`, CORS, `custom_openapi` (incl. the `SseEvent` reflection:
      `TypeAdapter(SseEvent)` → `components.schemas`), `app.openapi = custom_openapi`, and at the
      bottom `from wsh.api import routes  # noqa: F401` so importing `app` wires the routes.
- [x] `routes.py`: `chat` (incl. `is_safe_session_id`, the dangling-tool-call repair),
      `list_sessions`, `get_session`, `health`.
- [x] `main.py` re-imports `app` and the handlers.

**Verify:** `uv run pytest -q` → 32 passed.

## 8. Re-home + prune the tests
- [x] Split `tests/test_main.py` per the design's consolidation map into `test_models.py`,
      `test_tools.py`, `test_session_log.py`, `test_replay.py`, `test_meta.py`, `test_api.py`;
      imports change `main.X` → `wsh.X` (`main.datetime`/`main.timezone` → stdlib `datetime`/
      `timezone`).
- [x] One test per distinct behaviour; drop overlapping fixtures/assertions (target < 32).
- [x] `conftest.py`'s `sys.path` insert becomes unnecessary (the editable install exposes `wsh`);
      the no-ambient-reads guard stays unchanged.

**Verify:** `uv run pytest -q` → green with **fewer than 32** tests.

## 9. Thin `main.py` + `dump_openapi.py`
- [x] `main.py` → assembly only: `from wsh.api.app import app` (**< 60 lines**).
- [x] `dump_openapi.py` → `from wsh.api.app import app` (never `import main`).

**Verify:** `uv run pytest -q` → green. `uv run python dump_openapi.py /tmp/schema.json` succeeds.
`wc -l main.py` < 60. `python -c "import main; print(main.app.title)"` works, so
`uvicorn main:app` still does.

## 10. Frontend contract + docs
- [x] `pnpm run check:api` exits 0 — the schema is unchanged (no behaviour change), so
      `frontend/src/api-types.ts` regenerates with no diff.
- [x] `cd frontend && pnpm build` green.
- [x] README: backend run instructions → `uv sync` + `uv run uvicorn main:app --reload --port 8010`;
      layout diagram → thin `main.py`, `pyproject.toml`, code under `backend/src/wsh/`.
- [x] Add root `AGENTS.md` (minimal): `uv run pytest`, `uv run python dump_openapi.py …`,
      `pnpm build`, `pnpm run check:api`, and one line pointing at `plans/`.

**Verify:** `pnpm run check:api` exits 0 (no diff); `pnpm build` green; README/AGENTS.md updated.

## Notes from implementation (deltas from the plan as written)

- **`agent → session` is a real edge, not a phantom.** `agent_loop(messages, log: SessionLog)`
  keeps its `SessionLog` annotation, so `loop.py` imports `SessionLog` from `wsh.session`. The
  design graph was updated to include it.
- **Monkeypatching a moved scalar breaks `import back`.** Re-importing `from wsh.config import X`
  copies the value, so `monkeypatch.setattr(main, "BASH_TIMEOUT", 1)` no longer reached
  `run_bash` once it moved to `wsh/tools/bash.py`. The patch targets moved with the code: the
  timeout test now patches `wsh.tools.bash.BASH_TIMEOUT`, and the five `LOGS_DIR` tests patch
  `wsh.api.routes.LOGS_DIR`. (The "re-home" of step 8 therefore began in steps 5 and 7.)
- **`main.py` ended up 3 lines**, not just under 60: `from wsh.api.app import app`.
- **`models.py` is schemas-only** — the `TypeAdapter(SseEvent)` reflection lives in
  `api/app.py`'s `custom_openapi` (review decision 1).
- **`pydantic==2.14.1` added as an explicit dep** (it equals what `fastapi` already resolved).
- **Suite is 29 tests** (was 32): merged `bash` registry/schema and sync/async `call_tool` in
  `test_tools.py`; dropped three overlapping `prepare_session` tests (multi-tool-call message,
  header-only, continuation) already covered elsewhere; added a `health` endpoint test and a
  models discrimination smoke test.
- **`uv sync` bumped two transitive deps** (anyio 4.15.1→4.16.0, websockets 17.3→17.4); no
  behaviour change observed — 32→29 tests green and `check:api` diff clean.

## Done when
`uv run pytest` green before **and** after with fewer tests · `uv run python dump_openapi.py
/tmp/schema.json` succeeds · `pnpm run check:api` exits 0 · `backend/requirements*.txt` gone ·
`main.py` < 60 lines, assembly only · README + AGENTS.md updated · `git status --porcelain`
shows only the intended additions/renames/deletions.
