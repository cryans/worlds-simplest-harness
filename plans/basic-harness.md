# Plan: turn the hand-written tool schema into a `@tool` decorator

Status: ✅ complete

## Goal

Replace the hand-written `TOOLS = [...]` list in `backend/main.py` with a
`@tool` decorator that generates the OpenAI tool schema from a function's
name, docstring, and type hints — plus a name→function registry the agent
loop uses to dispatch calls. Update the frontend for generic tool events, add
tests, and document everything for mkdocs.

Each step below is **checkable**: run its `Verify` command and it must pass
before moving on.

---

## 1. Decorator + registry in `backend/main.py`

- [x] Add imports: `inspect`, `Callable`, `get_type_hints`, `Any`, `create_model`.
- [x] Add module state: `TOOLS: list[dict] = []` and `TOOL_REGISTRY: dict[str, Callable] = {}`.
- [x] Implement `tool(func)` decorator: name + docstring + type hints → pydantic schema → append to `TOOLS` and register in `TOOL_REGISTRY`.
- [x] Replace the hand-written `TOOLS = [...]` with `@tool async def bash(command: str) -> dict`.
- [x] Add `call_tool(func, args)` helper that awaits coroutines when needed.
- [x] Rewrite the agent-loop dispatch to look tools up in `TOOL_REGISTRY` and emit generic `{name, args}` / `{name, result}` events.

**Verify:**

```bash
cd backend && .venv/bin/python -c "import main; print(main.TOOLS[0]['function']['parameters'])"
```

prints a schema for `bash` with `properties.command.type == "string"` and
`required == ["command"]` — generated, not hand-written.

---

## 2. Generic tool events in `frontend/src/App.tsx`

- [x] Change `Step` to `{ name, args, result }` and `SseEvent` to carry `name`/`args`.
- [x] Push `{ name, args }` on `tool_call` events.
- [x] Render `$ <name> <args>` in `TurnView`.
- [x] Handle tool results that are errors (no stdout/stderr).

**Verify:**

```bash
cd frontend && pnpm build
```

type-checks and builds with no errors.

---

## 3. Tests in `backend/test_main.py`

- [x] Add `backend/requirements-dev.txt` (pytest).
- [x] `bash` is registered and its schema is correct.
- [x] The decorator registers a custom tool with required/optional params.
- [x] `call_tool` handles both sync and async functions.
- [x] `run_bash` captures stdout/exit code, runs in `sample-project/`, and times out.

**Verify:**

```bash
cd backend && .venv/bin/python -m pytest -q
```

all tests pass.

---

## 4. Docs for mkdocs

- [x] Add `mkdocs.yml` at the repo root with a `nav`.
- [x] Add `docs/index.md`, `getting-started.md`, `architecture.md`, `tools.md`.

**Verify:**

```bash
mkdocs build --strict   # or: mkdocs serve, then open the printed URL
```

builds with no broken links or missing pages.
