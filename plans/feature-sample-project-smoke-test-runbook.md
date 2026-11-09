---
feature: "sample-project-smoke-test"
status: "active"
references:
  - "plans/feature-sample-project-smoke-test-requirements.md"
  - "plans/feature-sample-project-smoke-test-design.md"
  - "plans/feature-sample-project-smoke-test-plan.md"
---

# Sample-project smoke test — runbook

A manual, real end-to-end check of the harness. No mocks. You drive it and you
judge pass/fail. The only persistent side effects are gitignored logs and a
disposable `/tmp/wsh-smoke-*` directory you delete by hand.

## 1. Start it

```bash
# terminal 1 — backend (from repo root)
cd backend
UV_CACHE_DIR=/tmp/uv-cache-wsh uv run uvicorn wsh.api.app:app --reload --port 8010

# terminal 2 — frontend
cd frontend
pnpm dev
```

Open <http://localhost:5173>. Check <http://localhost:8010/api/health> if you want
proof the backend is up.

## 2. Enter smoke mode

Start a **new chat** and send exactly:

```text
@sample-project
```

Expected:

- The turn renders as a normal user turn.
- The assistant reply contains `Smoke mode enabled. Ephemeral sandbox: /tmp/wsh-smoke-...`.
- The backend creates a directory named `/tmp/wsh-smoke-<session-prefix>-...`.
- The session log header records that same `sandbox` path.

The raw command should **not** be echoed to the model as a task; it is replaced by
the smoke notice. If you send `@sample-project do something`, the trailing text is
preserved as `First task: do something`.

### Turn smoke mode off

In the same session, send:

```text
@sample-project off
```

The session switches back to the normal `sample-project/` sandbox for the rest of
that conversation. The log keeps the original smoke header and appends a `sandbox`
override record; do not hand-edit that.

## 3. The four paths

### Path 1 — tool-call turn

Send a prompt that forces the model to use `bash`, for example:

```text
Run `pwd`, create a file called smoke.txt, and then list the directory.
```

Watch for, in order: `session` → `status` → `tool_call` / `tool_result` → `answer`.
Then inspect:

```bash
ls -la /tmp/wsh-smoke-*   # pick the newest one for this session
cat /tmp/wsh-smoke-*/smoke.txt
```

The file must be inside the `/tmp` sandbox, **not** in the repo's `sample-project/`.

### Path 2 — no-tool answer

Send a plain question:

```text
Say hello in one short sentence.
```

Expected: a single `answer`, no tool steps, no `tool_call`/`tool_result`.

### Path 3 — resume and continue

Leave the session (open another session or reload), then reopen it from the
sidebar. Send a follow-up that builds on the previous turn, for example:

```text
Now list the files we created earlier.
```

Expected: the session reuses the **same** `/tmp/wsh-smoke-*` directory (check the
header in the JSONL again if unsure), and the transcript shows the earlier turns.

### Path 4 — error path (optional)

Temporarily unset/blank `DEEPSEEK_API_KEY` and send a prompt. The UI should render
the `error` event text. Restore the key afterwards.

## 4. Evidence to inspect

- **UI transcript** — the SSE events should render in order, no blank turns.
- **Session log** — `logs/{session_id}.jsonl`. The first `session` record should
  carry `"sandbox": "/tmp/wsh-smoke-..."`.
- **Ephemeral sandbox** — `/tmp/wsh-smoke-*`. All `bash` side effects land here.
- **Server log** — `logs/uvicorn.log`, for any tracebacks.

## 5. Cleanup

Delete the smoke sandbox by hand when you're done:

```bash
rm -rf /tmp/wsh-smoke-*
```

The session log stays in the gitignored `logs/` directory, like any other session.

## Pass criterion

Your own observation: every event renders, the smoke work happened in `/tmp` and
not `sample-project/`, resume reuses the same sandbox, and `git status --porcelain`
shows no tracked changes caused by the run.
