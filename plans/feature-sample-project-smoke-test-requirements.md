---
feature: "sample-project-smoke-test"
status: "proposed"
references:
  - "plans/next-steps.md"
---

# Sample-project smoke test — requirements

**Goal.** Give the harness an explicit, repeatable, human-driven **smoke mode** for
exercising the harness itself: real backend, real frontend, real DeepSeek model, and
the real `bash` tool — but with an **ephemeral sandbox** under `/tmp` instead of the
persistent repo-root `sample-project/`.

**Agreed mechanism.** Smoke mode is entered with a real prompt, not an env var or
global flag. If a **new session's first user message** starts with `@sample-project`,
that session is in smoke mode. The harness recognizes the command, creates the
session's ephemeral sandbox, and the mode persists for that session only. Normal mode
remains the default.

**Why now.** Today the only smoke test is ad-hoc and implicit (`docs/smoke-test.md`,
currently untracked). It drives the live `sample-project/`, so every run leaves state
behind and the sandbox diverges. Separately, `wsh/config.py` creates `sample-project/`
as an import-time side effect — an old experiment that pollutes the repo and even
`dump_openapi.py`/tests. The retros already flagged this: *"the sandbox is gitignored
but coupled to the repo root; it pollutes and diverges."*

## Requirements

1. **Smoke mode is a real, end-to-end exercise.**
   The smoke run uses the actual FastAPI backend, the actual React frontend, the real
   DeepSeek API, and the real `bash` tool. No stubs, mocks, or fake model calls.

2. **Smoke mode is entered by the `@sample-project` command.**
   When a new session's first user message starts with `@sample-project`, the harness
   enters smoke mode for that session. Normal mode is the default; nothing global is
   set. Subsequent turns in the same session stay in smoke mode.

3. **The smoke sandbox is ephemeral and lives under `/tmp`.**
   A smoke session gets a fresh project directory under `/tmp` (e.g.
   `/tmp/wsh-smoke-<id>`), and all `bash` tool calls in that session run there. The
   directory is **left in place after the run** so the driver can inspect it; the
   driver deletes it manually when done. It must not reuse or write to the persistent
   `sample-project/`.

4. **The command is a harness command, not a model task.**
   The raw `@sample-project` text is not sent verbatim to DeepSeek as the user's task.
   The harness replaces it with a short notice (including the ephemeral sandbox path)
   before the model is called, so the model knows where it is working and the normal
   loop still runs.

5. **`config` no longer creates the sandbox.**
   Importing `wsh.config` — and therefore importing `wsh.api.app`, running tests, or
   dumping the OpenAPI schema — must not `mkdir` `sample-project/` or any sandbox
   directory. Sandbox creation moves out of import time (to smoke-mode setup, the
   first tool call, or another explicit point decided in design).

6. **Smoke mode is white-box and user-driven.**
   The human driver operates the browser and inspects the run while it happens.
   "Assistance" means a written runbook and easy access to the evidence — not an
   automated test. The driver decides pass/fail from their own observation.

7. **The driver can see the whole loop.**
   During a smoke run the driver can inspect:
   - the normal UI transcript (SSE events in order: `session` → `status` →
     `tool_call`/`tool_result` → `answer`, plus `error` on failure),
   - the session JSONL log under `logs/{session_id}.jsonl`,
   - the ephemeral sandbox contents under `/tmp`,
   - the backend server log (`logs/uvicorn.log`).
   These are enough to verify the loop at each stage, white-box style.

8. **The runbook lives in `plans/` only.**
   The steps to enter smoke mode, the prompts to run, the expected observations for
   each path, and the pass criteria are documented in `plans/` for now. No README/docs
   changes yet.

9. **A smoke run is nearly side-effect free.**
   The only side effects are the disposable `/tmp` sandbox directory and gitignored
   logs. After a run, `git status --porcelain` shows no tracked changes.

## Out of scope

- Automated smoke tests / CI invocation of the smoke run.
- Stubbing or mocking the model or the `bash` tool.
- A general configurable sandbox path (`SAMPLE_PROJECT_DIR`/`WSH_SANDBOX`).
- Making `manage_plan` sandbox-aware in this pass (smoke mode primarily exercises
  `bash`; note if the model calls `manage_plan`, its current cwd-relative behaviour is
  unchanged).
- Moving, deleting, or reusing `sample-project/`, `sample-project-2/`, or
  `sample-project-old/` (leave them unless explicitly asked).
- README/docs/mkdocs updates — plans only for now.
- `harness-guardrails`, `document-sdlc`, `mermaid-validation`.

## Acceptance criteria

- `python -c "import wsh.config"` creates no sandbox directory and no
  `sample-project/` side effect.
- Smoke mode is off by default; normal mode starts as it does today (apart from the
  import-time `mkdir` removal).
- Starting a new session whose first user message is `@sample-project` creates a
  `/tmp` sandbox for that session; later turns in the same session keep using it.
- The model never receives the raw `@sample-project` command; it is replaced before
  the model call, and the system prompt names the session's actual sandbox path.
- A real smoke run against DeepSeek exercises the tool-call path and the no-tool path;
  the driver observes the expected SSE sequence and can inspect the JSONL log,
  server log, and the `/tmp` sandbox left behind.
- The smoke run does not write into the persistent `sample-project/` and leaves no
  tracked changes (`git status --porcelain` clean apart from intended plan artifacts).
- The existing backend test suite is still green after the config change (tests are
  adapted if they currently depend on import-time sandbox creation).
- The runbook in `plans/` covers, at minimum, the four paths from the current manual
  smoke test: a tool-call turn, a no-tool answer, a resume/continue turn, and
  (optionally) an error path.

## Open questions for design

1. **Normal-mode sandbox behaviour.** Once `config` stops creating the sandbox, should
   a normal run fail clearly if `sample-project/` is missing, or create it lazily on
   the first `bash` call?
2. **Smoke sandbox naming.** Should the `/tmp` directory use a fixed name (easy to
   find, overwritten each run) or a unique per-run name (e.g. `/tmp/wsh-smoke-<id>`)?
   The driver wants to inspect it after the run and delete it manually.
3. **`manage_plan` in smoke mode.** Do we accept that `manage_plan` remains
   cwd-relative and could write outside the `/tmp` sandbox, or is that a small
   follow-up inside this feature?
4. **Prompt seed.** Is the smoke run freeform (driver invents prompts from the runbook)
   or should the runbook carry a fixed, known-good prompt/seed project? Current answer:
   user-driven, so the runbook suggests prompts but does not automate them.
