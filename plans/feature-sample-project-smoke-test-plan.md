---
feature: "sample-project-smoke-test"
status: "proposed"
references:
  - "plans/feature-sample-project-smoke-test-requirements.md"
  - "plans/feature-sample-project-smoke-test-design.md"
---

# Sample-project smoke test — implementation plan

Requirements: `feature-sample-project-smoke-test-requirements.md`.
Design: `feature-sample-project-smoke-test-design.md`.

Tick each box only once its **Verify** passes; don't start the next step until it does.

> **Sandbox note:** `~/.cache/uv` is read-only in this harness, so plain `uv run` can fail to
> lock its cache. Prefix `UV_CACHE_DIR=/tmp/uv-cache-wsh` for every `uv run` below.

## 1. Baseline

- [x] Confirm current branch and clean-ish tree (only the intended plan docs and the
      author's pre-existing untracked files).
- [x] Record the before test count.

**Verify:**

```bash
cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run pytest -q
# expected: 43 passed (1 starlette DeprecationWarning)
```

## 2. `config.py` — remove import-time mkdir, add sandbox context

- [x] Delete `SAMPLE_PROJECT.mkdir(exist_ok=True)`.
- [x] Add `from contextvars import ContextVar`.
- [x] Add `_current_sandbox` (`ContextVar[Path]`, default `SAMPLE_PROJECT`).
- [x] Add `set_current_sandbox(path)` (return the reset token) and `get_current_sandbox()`.
- [x] Replace the fixed `SYSTEM_PROMPT` with `SYSTEM_PROMPT_TEMPLATE` (using `{sandbox}`)
      and `make_system_prompt(sandbox: Path = SAMPLE_PROJECT) -> str`.

**Verify:**

```bash
cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run python - <<'PY'
import wsh.config as c
print(c.make_system_prompt())
print(c.get_current_sandbox())
PY
```

```bash
cd .. && rm -rf sample-project && cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run python -c "import wsh.config" && cd .. && test ! -e sample-project && mkdir -p sample-project
```

## 3. `session/log.py` — persist and resume the session sandbox

- [x] Import `SAMPLE_PROJECT`.
- [x] Add optional `sandbox: Path | None = None` to `SessionLog.__init__`.
- [x] Set `self.sandbox` from the parameter or `SAMPLE_PROJECT` before `_resume()`.
- [x] In `_resume()`, when a `session` record has a `sandbox` field, set
      `self.sandbox = Path(record["sandbox"])`.

**Verify:**

```bash
cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run pytest -q
# still 43 passed
```

```bash
cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run python - <<'PY'
import tempfile, pathlib
from wsh.session import SessionLog
with tempfile.TemporaryDirectory() as d:
    log = SessionLog("s", logs_dir=pathlib.Path(d), sandbox=pathlib.Path("/tmp/example"))
    log.write_session("m", "http://x", str(log.sandbox), {}, "sys", [])
    log2 = SessionLog("s", logs_dir=pathlib.Path(d))
    assert log2.sandbox == pathlib.Path("/tmp/example")
    print(log2.sandbox)
PY
```

## 4. `tools/bash.py` — run in the current session sandbox

- [x] Import `get_current_sandbox` instead of `SAMPLE_PROJECT`.
- [x] In `run_bash`, compute `sandbox = get_current_sandbox()`, then
      `sandbox.mkdir(parents=True, exist_ok=True)`.
- [x] Pass `cwd=sandbox` to `create_subprocess_shell`.

**Verify:**

```bash
cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run pytest -q
# still 43 passed
```

```bash
cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run python - <<'PY'
import asyncio, tempfile, pathlib
from wsh.config import set_current_sandbox
from wsh.tools import run_bash
async def main():
    with tempfile.TemporaryDirectory() as d:
        token = set_current_sandbox(pathlib.Path(d))
        try:
            result = await run_bash("pwd")
        finally:
            set_current_sandbox(pathlib.Path("."))  # reset is only for this scratch check
        assert d in result["stdout"], result
        print(result["stdout"].strip())
asyncio.run(main())
PY
```

## 5. `agent/loop.py` — activate the session sandbox before tools run

- [x] Import `SAMPLE_PROJECT` and `set_current_sandbox`.
- [x] At the top of `agent_loop`, call
      `set_current_sandbox(getattr(log, "sandbox", SAMPLE_PROJECT))`.

**Verify:**

```bash
cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run pytest -q
# still 43 passed; no loop behavior change yet
```

## 6. `api/routes.py` — recognize `@sample-project` and set up the smoke sandbox

- [x] Import `tempfile`, `Path`, and `make_system_prompt` (replace the `SYSTEM_PROMPT`
      import; keep `SAMPLE_PROJECT` for `/api/health` and normal-mode defaults).
- [x] Add `SMOKE_COMMAND = "@sample-project"`.
- [x] Add helpers:
  - `_first_user_message(messages)`
  - `_is_smoke_command(messages)` — exact `@sample-project` or prefix `@sample-project `.
  - `_replace_smoke_command(messages, sandbox)` — replace the first user command with
    `Smoke mode enabled. Ephemeral sandbox: <sandbox>.`; preserve trailing text as
    `First task: <rest>`.
  - `_new_smoke_sandbox(session_id)` — thin `tempfile.mkdtemp` wrapper, kept separate
    so tests can monkeypatch it without touching the real `tempfile`.
- [x] In `chat()`:
  1. Build `log = SessionLog(session_id)`.
  2. If smoke command and `not log.path.exists()`, set
     `log.sandbox = Path(_new_smoke_sandbox(session_id))`.
  3. `system_prompt = make_system_prompt(log.sandbox)`.
  4. `log.write_session(..., sandbox=str(log.sandbox), system_prompt=system_prompt, ...)`.
  5. Build `convo` without system messages; run `_replace_smoke_command` when the
     command is present.
  6. Prepend the dynamic system prompt and stream `agent_loop` as before.

**Verify:**

```bash
cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run pytest -q
# still 43 passed
```

```bash
cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run python - <<'PY'
from wsh.api.routes import _is_smoke_command, _replace_smoke_command
import pathlib
assert _is_smoke_command([{"role": "user", "content": "@sample-project"}])
assert _is_smoke_command([{"role": "user", "content": "@sample-project do the thing"}])
assert not _is_smoke_command([{"role": "user", "content": "hello"}])
out = _replace_smoke_command([{"role": "user", "content": "@sample-project"}], pathlib.Path("/tmp/s"))
assert "@sample-project" not in out[0]["content"]
print(out[0]["content"])
PY
```

## 7. Tests for the new behavior

- [x] `test_session_log.py`: add resume-sandbox-from-header and default-sandbox tests.
- [x] `test_tools.py`: add a test that `run_bash` runs in `get_current_sandbox()` when
      the context var is set; keep the existing cwd/stdout test green.
- [x] `test_api.py`: add helper tests for `_is_smoke_command` and
      `_replace_smoke_command`.
- [x] `test_api.py`: add a smoke-route test (monkeypatch `agent_loop` and
      `_new_smoke_sandbox`) asserting the header records the ephemeral sandbox and the
      model messages do not contain the raw command.
- [x] `test_api.py`: add a normal-route test asserting the default session sandbox is
      still `SAMPLE_PROJECT`.

**Verify:**

```bash
cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run pytest -q
# expected: 50 passed (43 baseline + 7 new); record the actual number
```

## 8. Full verification

- [x] `cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run pytest -q` — green.
- [x] `cd frontend && pnpm build` — green (no frontend changes, but proves none broke).
- [x] `cd frontend && pnpm run check:api` — exits 0 (no API schema drift expected).

**Verify:**

```bash
cd backend && UV_CACHE_DIR=/tmp/uv-cache-wsh uv run pytest -q
cd ../frontend && pnpm build && pnpm run check:api
```

## 9. Write the smoke runbook in `plans/`

- [x] Add `plans/feature-sample-project-smoke-test-runbook.md` with:
  - how to start backend + frontend,
  - how to enter smoke mode with `@sample-project`,
  - the four paths: tool-call turn, no-tool answer, resume/continue, optional error,
  - what to inspect after the run (UI transcript, `logs/{session_id}.jsonl`,
    `/tmp/wsh-smoke-*`, `logs/uvicorn.log`),
  - pass criterion: driver's own judgment, and manual deletion of the `/tmp` sandbox.

**Verify:**

```bash
test -f plans/feature-sample-project-smoke-test-runbook.md
grep -q "@sample-project" plans/feature-sample-project-smoke-test-runbook.md
grep -q "/tmp/wsh-smoke-" plans/feature-sample-project-smoke-test-runbook.md
```

## 10. Manual smoke run (real DeepSeek + real browser)

Do not tick until you have actually run it.

- [x] Start backend + frontend from the runbook.
- [x] New chat → send `@sample-project`; confirm the session enters smoke mode and the
      reply names the `/tmp` sandbox.
- [x] Send a tool-call prompt; confirm `session → status → tool_call/tool_result →
      answer` renders in order.
- [x] Inspect the `/tmp/wsh-smoke-*` directory and the session JSONL; confirm the
      `bash` work happened there and the header `sandbox` points at it.
- [x] Send a no-tool prompt; confirm a plain `answer` renders with no tool steps.
- [x] Leave and resume the session; confirm it still uses the same smoke sandbox.
- [x] Delete the `/tmp/wsh-smoke-*` directory manually.

**Verify:** your own observation; no automated pass.

## 11. Retro + next-steps

- [x] Write `plans/feature-sample-project-smoke-test-retro.md` (measured before/after,
      what went well/didn't, decisions).
- [x] Update `plans/next-steps.md`: mark this feature done/active appropriately, and
      keep or amend `sample-project-rework` as needed.
- [x] `git status --porcelain` shows only intended plan docs and code changes.

**Verify:**

```bash
cd .. && git status --porcelain
```

---

## Notes / risks from the plan

- **Step 2 temporarily deletes `sample-project/`** to prove the import has no side
  effect. Recreate it afterwards if you want normal-mode use; the `bash` tool will
  recreate it lazily anyway.
- **Actual final test count:** 51 (43 baseline + 6 initial feature tests + 2
  off-switch tests). The original 50 forecast was close but not exact.
- **`manage_plan` is not sandboxed** in this feature (per design). The runbook should
  drive `bash`-only prompts.
