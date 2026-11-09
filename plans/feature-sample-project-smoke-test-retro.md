---
feature: "sample-project-smoke-test"
status: "complete"
references:
  - "plans/feature-sample-project-smoke-test-requirements.md"
  - "plans/feature-sample-project-smoke-test-design.md"
  - "plans/feature-sample-project-smoke-test-plan.md"
  - "plans/feature-sample-project-smoke-test-runbook.md"
---

# Sample-project smoke test — retro

## Evidence (measured, not remembered)

| Measure | Before | After |
|---|---|---|
| Backend tests | 43 | **51** (green) |
| Import-time sandbox creation | `SAMPLE_PROJECT.mkdir(exist_ok=True)` on `import wsh.config` | **none** (verified by rm/import/check) |
| Session sandbox | hardcoded global `SAMPLE_PROJECT` | `SessionLog.sandbox`, resumed from the log header |
| `bash` cwd | module global `SAMPLE_PROJECT` | `ContextVar` current sandbox |
| System prompt | fixed `SYSTEM_PROMPT` | `make_system_prompt(sandbox)` per session |
| Smoke mode | ad-hoc manual doc, persistent `sample-project/` | `@sample-project` command, ephemeral `/tmp/wsh-smoke-*` |
| Off switch | none | `@sample-project off` + appended `sandbox` override record |
| Frontend | — | **no changes** (`pnpm build`, `check:api` clean) |
| Manual smoke | — | driver-verified: `@sample-project` worked |

## What went well

1. **The command fit the existing loop without a redesign.** The whole feature is a
   pre-loop branch in `routes.chat` plus a `ContextVar` read by `bash`. No new tool,
   no new endpoint, no new event, no frontend change.
2. **`SessionLog` was already the right persistence point.** The `session` header
   already carried a `sandbox` field; making `SessionLog` resume it meant session
   specificity came almost for free.
3. **The runbook stayed manual on purpose.** The driver could watch the UI and inspect
   `/tmp`, the JSONL, and the server log — which is exactly the white-box gate that
   matters for this harness.
4. **The command stayed out of the model's mouth.** Replacing `@sample-project` with a
   smoke notice kept DeepSeek from having to interpret a harness instruction.

## What didn't go well / limitations

1. **This is a working-directory mode, not a true sandbox.** `bash` gets `cwd=` in a
   `/tmp` directory, but a command can still `cd ../..` or address absolute paths.
   That's acceptable for the current smoke-test purpose, but it must not be confused
   with a security boundary.
2. **`manage_plan` is still cwd-relative and not sandboxed.** A smoke prompt that
   leads the model to call `manage_plan` can write outside `/tmp`. The runbook steers
   toward `bash` prompts for now.
3. **The plan forecast 50 tests; actual is 49.** The test-count arithmetic was off by
   one again (the API step added three tests, not four). Caught by running, not by the
   plan.
4. **Normal mode is still coupled to repo-root `sample-project/`.** This feature fixed
   the smoke-run pollution, not the original `sample-project-rework` goal of an
   env-configurable, out-of-repo default sandbox.

## Learned

- **A `ContextVar` is the right size for per-session tool state here.** It keeps the
  `@tool` registry and `call_tool` untouched while still being session/task-scoped.
- **Persist session mode where the session is already persisted.** The log header was
  the correct place, and `SessionLog.sandbox` made later turns resume without extra
  request fields.
- **Manual white-box smoke still earns its keep.** The browser rendered the command
  turn and the driver confirmed the behavior; no automated test replaced that.

## Review (implementer)

- **Well:** the command semantics were easy to reason about because all special-casing
  is in `routes.chat`; the rest of the loop stayed exactly the same.
- **Didn't:** I initially forgot that `SessionLog` uses its own imported `LOGS_DIR`,
  so the new route tests wrote to the real `logs/` until `chat` passed `logs_dir`
  explicitly. The no-ambient-reads guard caught it.
- **Learned:** when a constructor has a default path, tests need to monkeypatch the
  module the constructor reads, or the caller must pass the path explicitly.

## Actions

1. **`true-sandbox` is the next feature** — use `bwrap` to make the smoke sandbox a
   real filesystem boundary (see `plans/feature-true-sandbox-requirements.md`).
2. **`sample-project-rework` remains open** — normal mode is still coupled to
   repo-root `sample-project/` and not env-configurable.
3. **`manage_plan` sandbox-awareness** — fold into `true-sandbox` or
   `harness-guardrails`; it is still cwd-relative and not sandboxed.
