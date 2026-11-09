---
feature: "true-sandbox"
status: "proposed"
references:
  - "plans/feature-sample-project-smoke-test-retro.md"
  - "plans/feature-event-loop-cleanup-requirements.md"
  - "plans/feature-event-loop-cleanup-retro.md"
  - "plans/next-steps.md"
---

# True sandbox for smoke-mode `bash` — requirements

**Goal.** Make the smoke-mode `bash` tool an actual filesystem boundary: the model's
shell commands can read only a small allowlist of system/toolchain paths and can write
only inside the session's `/tmp/wsh-smoke-*` directory. No bash parser.

**Why now.** The current smoke mode is a working-directory change, not a sandbox. A
command can `cd ../..`, read the repo, or write to absolute paths. `bwrap` (bubblewrap)
is already installed, user namespaces work, and a proof-of-concept shows `uv init` /
`uv run` succeeding inside a bwrap namespace.

**Non-negotiable plugin boundary.** Smoke-testing is a plugin concern, not a change to
the main agent loop. See `feature-event-loop-cleanup-requirements.md` and its retro:
the loop *is* the design, and smoke-only branches would undo that cleanup.

## Requirements

1. **Smoke mode is a plugin with its own modules.**
   The smoke-test/sandbox implementation lives in its own module(s) (for example
   `wsh/plugins/smoke/`), not scattered through the main loop or chat route.

2. **The main event loop is not touched.**
   `wsh/agent/loop.py` must remain free of smoke-specific code. If the current
   smoke-mode implementation has already leaked into the loop (it has), this feature
   extracts it behind the plugin boundary first.

3. **The chat route has no smoke-specific branches.**
   `wsh/api/routes.py` may register or invoke a plugin through a small seam, but it
   must not grow `if smoke:` command parsing, sandbox setup, or message rewriting.

4. **Smoke-mode `bash` runs under `bwrap`.**
   In smoke mode, the plugin's `run_bash` invokes the command through `bwrap` instead
   of a bare `create_subprocess_shell`.

5. **The command string is not parsed.**
   The existing command string is passed to `bash -lc` inside the sandbox. The
   filesystem boundary comes from the kernel mount namespace, not from interpreting
   the command.

6. **Filesystem allowlist.**
   The bwrap invocation read-only binds at least:
   - `/usr`, `/lib`, `/lib64`, `/bin`, `/etc`
   - the uv toolchain: `~/.local/bin` and `~/.local/share/uv`
   It binds the session's smoke sandbox as `/workspace` (read-write) and sets
   `--chdir /workspace`. The repo and the rest of `$HOME` are not visible.

7. **Model-facing path is `/workspace`.**
   In smoke mode the system prompt and smoke notice tell the model its project folder
   is `/workspace`. The JSONL header still records the host `/tmp/wsh-smoke-*` path for
   the driver to inspect.

8. **Missing `bwrap` is a clear failure.**
   If `bwrap` is not available, smoke mode returns a clear error/status instead of
   silently falling back to the current cwd-only behavior.

9. **`manage_plan` cannot escape the sandbox.**
   During smoke mode, either `manage_plan` is routed through the same sandbox or it is
   not offered to the model. Leaving it cwd-relative would defeat the boundary.

10. **Normal mode is unchanged.**
    Non-smoke sessions keep today's behavior. This feature is only the smoke-mode
    filesystem boundary.

## Out of scope

- Normal-mode sandbox path/env-config (`sample-project-rework`).
- Parsing or validating bash syntax.
- seccomp/landlock/BPF hardening beyond bwrap mount namespaces.
- Applying bwrap to all modes (could be a later generalization).
- Network policy for normal mode.
- Refactoring unrelated tools; only the smoke plugin boundary needed here.

## Acceptance criteria

- Smoke code lives in its own plugin module(s); `wsh/agent/loop.py` has no smoke code.
- `wsh/api/routes.py` has no smoke-specific parsing/setup/rewrite branches.
- In a smoke session, `cat /home/duben/...` and `touch /etc/evil` fail or see nothing.
- `uv init` and `uv run python -c "..."` still work inside the smoke sandbox.
- All smoke-mode writes land under the host `/tmp/wsh-smoke-*` directory.
- The model sees `/workspace` as its project folder; the JSONL records the host path.
- If `bwrap` is missing, smoke mode fails clearly rather than running unsandboxed.
- Existing backend tests stay green (updated as needed).

## Open questions

1. **Plugin seam.** What is the smallest registration seam in `wsh/api/routes.py`:
   a command-handler registry, a plugin hook, or something else?
2. **Network.** Should smoke mode start with `--unshare-net` (stricter) or leave
   network enabled for `uv add`/package downloads?
3. **uv cache.** Use a workspace-local `UV_CACHE_DIR=/workspace/.uv-cache`, or
   read-only bind the host uv cache for speed?
4. **`manage_plan`.** Route it through the same sandbox, or hide it in smoke sessions?
5. **Path model.** Confirm `/workspace` is acceptable to expose to the model instead
   of the host `/tmp/wsh-smoke-*`.
