---
branch: "backend-refactor"
feature: "backend-refactor"
status: "complete"
references:
  - "plans/feature-backend-refactor-requirements.md"
  - "plans/feature-backend-refactor-design.md"
  - "plans/feature-backend-refactor-plan.md"
---

# Backend refactor — retro

## Evidence (measured, not remembered)

| Measure | Before | After |
|---|---|---|
| `backend/main.py` | 955 lines | **3 lines** |
| Tests | 32 | **29** (green) |
| Backend modules | 1 file | **13 modules + 5 `__init__.py`** under `src/wsh/` |
| Deps | `requirements*.txt` | `pyproject.toml` (explicit `pydantic`, no lockfile) |
| Wire contract | — | `check:api` regenerates `api-types.ts` **byte-identical** |

Duration: much longer than the ~2 hours expected.

## What went well

1. **The split stayed green at every step** (extract → import-back → re-home → thin). Each
   step's **Verify** was answerable in seconds, so "is step N done?" never depended on opinion.
2. **The dependency graph landed because of the human loop.** Drawing it, photographing it,
   Gemini → mermaid, then feeding it back produced the surface/domain/foundation layering — a
   clear improvement over the flat arrow list that preceded it. The human interaction is what
   made it work.
3. **"Playing it through" beat the paper graph.** Reality exposed the phantom `session → sse`
   edge (a misfiled `now_iso`) and the real `agent → session` edge (the `SessionLog` annotation
   on `agent_loop`) that the prose analysis had both called wrong.
4. **The contract check proved "no behaviour change" mechanically** — the regenerated
   `api-types.ts` was byte-identical, so the wire shape never moved.

## What didn't go well

1. **It took far longer than expected.** The review conversation and diagram iteration paid off,
   but "playing it through" also surfaced deltas the plan hadn't anticipated (monkeypatch targets
   on moved scalars, the `agent → session` edge).
2. **Model-failure recovery isn't working — the worst finding.** When DeepSeek returns 503 or the
   connection drops, the turn dies with an empty `Could not reach the model: ` message (the bare
   `except Exception as e` prints `str(e)`, which is empty), no retry, and the turn is left
   "incomplete" (`session ended mid-turn — no answer was recorded`).
3. **`step` resets to 1 every turn, and error replay keys on it.** `agent_loop` runs
   `for step in range(1, MAX_STEPS + 1)` fresh each turn; `prepare_session` keys errors by
   `step`, so errors from different turns collide and only the **last** turn gets an error
   attached. Pre-existing (the refactor moved it verbatim), but now it has evidence: session
   `4a3bd8de`, three consecutive failures, all `step: 1`.
4. **`sample-project` lives in the main repo.** It's gitignored but `config.py` hardcodes it at
   the repo root. It was genuinely useful as a live sandbox, but it shouldn't be part of the
   project — and its persistence is what made the fibonacci run diverge (4 tests vs ~20, and the
   `uv` "not packaged" error: the agent ran `uv` in a sandbox with no `pyproject.toml`).

## More of that in the future

- Human-in-the-loop diagrams (draw → photograph → mermaid → feed back). Better than writing
  mermaid cold.
- "Play it through" over paper dependency graphs.
- Keep the per-step **Verify** discipline.

## Decision archaeology

| Decision | Consequence | Would have been caught by |
|---|---|---|
| Defer retry ("no behaviour change") | Failures kill the turn; opaque/empty error; incomplete turns pile up | An `errored` turn state (F4) + one smoke call against the real provider |
| `step` = per-turn round-trip counter | Error replay keyed by `step` collides across turns | A multi-turn failure fixture (session `4a3bd8de` is now one) |
| `f"…{e}"` for a bare `except Exception` | Empty message when `str(e) == ""`; exception type lost | Include `type(e).__name__`; a mocked empty-message transport-error test |
| `import back` to keep `main.X` green | Monkeypatching a moved scalar (`BASH_TIMEOUT`, `LOGS_DIR`) broke | N/A — caught and fixed during the move |
| `sample-project` at repo root | Sandbox coupled to the repo; divergent runs from accumulated state | An env-configurable sandbox path outside the repo |

## Review (implementer)

- **Well:** the per-step **Verify** kept the suite green after every move, so the mechanical split
  never carried a broken state; the extract → import-back → re-home → thin order was the right shape.
- **Didn't:** I called `agent → session` a phantom, but the `SessionLog` annotation makes it real —
  "just build it" beat my static reasoning. And the plan's "green every step" promise missed the
  monkeypatch-on-a-copied-scalar case.
- **Learned:** a mechanical move needs the reality check (running it), not just review (reading it).

## Actions

1. **`model-failure-handling`** — retry on 503/connection + non-empty error messages (small, next).
2. **`session-domain`** — turn state machine, per-turn error attachment, `step` semantics.
3. **`sample-project-rework`** — env-configurable sandbox path, out of the repo.
4. `plans/next-steps.md` now stands alone; `backend-refactor` is done.
