---
title: "plans/backlog-nameable-sessions-requirements.md"
feature: "nameable-sessions"
status: "proposed"
references:
  - "plans/backlog.md"
  - "plans/backlog-agent-run-visibility-requirements.md"
  - "plans/backlog-token-usage-and-cost-requirements.md"
---

# Nameable sessions — requirements

**Goal.** Let the developer give a session a meaningful name/title, instead of showing only a
date and a truncated UUID in the sidebar.

**Why now.** The session list renders `fmt(updated_at)` and `id.slice(0, 5)` — two runs are
indistinguishable by date alone, which breaks down once a few debugging sessions pile up.

## Requirements

1. **Durable name.** Each session can carry a human-assigned name that persists across app
   and server restarts (not React state).
2. **Listed and displayed.** The name appears in the session sidebar (replacing or preceding
   the date) and in the session detail view.
3. **Editable.** The developer can rename a session from the UI (inline edit / double-click).
4. **Graceful default.** Sessions without a name keep a sensible fallback (e.g. date, or the
   first prompt's `preview`) until renamed.

## Gaps to close (not yet present)

- **No `name` field.** `SessionMeta`/`SessionPayload` (`wsh/models.py`) have no display-name
  field; the sidebar shows only date + first 5 UUID chars.
- **No mutation endpoint.** Session APIs are read-only today (`GET /api/sessions`,
  `GET /api/sessions/{id}`). Renaming needs a first mutation (e.g. `PATCH /api/sessions/{id}`).
- **Persistence mechanism.** The JSONL WAL is append-only with a one-time header
  (`write_session` writes only when `seq == 0`), so a rename needs an append-only `rename`
  event (or an equivalent sidecar) rather than rewriting the header.
- **Naming source.** Decide the default when unnamed (auto-name from first prompt? keep date?).

## Related

- `live-token-usage-and-cost` / `agent-run-visibility` — all improve the session list/detail UX.
