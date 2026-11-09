---
feature: "true-sandbox"
status: "proposed"
references:
  - "plans/feature-sample-project-smoke-test-retro.md"
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

## Requirements

1. **Smoke-mode `bash` runs under `bwrap`.**
   In smoke mode, `run_bash` invokes the command through `bwrap` instead of a bare
   `create_subprocess_shell`.

2. **The command string is not parsed.**
   The existing command string is passed to `bash -lc` inside the sandbox. The
   filesystem boundary comes from the kernel mount namespace, not from interpreting
   the command.

3. **Filesystem allowlist.**
   The bwrap invocation read-only binds at least:
   - `/usr`, `/lib`, `/lib64`, `/bin`, `/etc`
   - the uv toolchain: `~/.local/bin` and `~/.local/share/uv`
   It binds the session's smoke sandbox as `/workspace` (read-write) and sets
   `--chdir /workspace`. The repo and the rest of `$HOME` are not visible.

4. **Model-facing path is `/workspace`.**
   In smoke mode the system prompt and smoke notice tell the model its project folder
   is `/workspace`. The JSONL header still records the host `/tmp/wsh-smoke-*` path for
   the driver to inspect.

5. **Missing `bwrap` is a clear failure.**
   If `bwrap` is not available, smoke mode returns a clear error/status instead of
   silently falling back to the current cwd-only behavior.

6. **`manage_plan` cannot escape the sandbox.**
   During smoke mode, either `manage_plan` is routed through the same sandbox or it is
   not offered to the model. Leaving it cwd-relative would defeat the boundary.

7. **Normal mode is unchanged.**
   Non-smoke sessions keep today's behavior. This feature is only the smoke-mode
   filesystem boundary.

## Out of scope

- Normal-mode sandbox path/env-config (`sample-project-rework`).
- Parsing or validating bash syntax.
- seccomp/landlock/BPF hardening beyond bwrap mount namespaces.
- Applying bwrap to all modes (could be a later generalization).
- Network policy for normal mode.

## Acceptance criteria

- In a smoke session, `cat /home/duben/...` and `touch /etc/evil` fail or see nothing.
- `uv init` and `uv run python -c "..."` still work inside the smoke sandbox.
- All smoke-mode writes land under the host `/tmp/wsh-smoke-*` directory.
- The model sees `/workspace` as its project folder; the JSONL records the host path.
- If `bwrap` is missing, smoke mode fails clearly rather than running unsandboxed.
- Existing backend tests stay green (updated as needed).

## Open questions

1. **Network.** Should smoke mode start with `--unshare-net` (stricter) or leave
   network enabled for `uv add`/package downloads?
2. **uv cache.** Use a workspace-local `UV_CACHE_DIR=/workspace/.uv-cache`, or
   read-only bind the host uv cache for speed?
3. **`manage_plan`.** Route it through the same sandbox, or hide it in smoke sessions?
4. **Path model.** Confirm `/workspace` is acceptable to expose to the model instead
   of the host `/tmp/wsh-smoke-*`.
