---
schema: "feature-load-jsonl-retro"
feature: "load-jsonl"
phase: "Review"
status: "complete"
references:
  - "plans/feature-load-jsonl-requirements.md"
  - "plans/feature-load-jsonl-design.md"
  - "plans/feature-load-jsonl-plan.md"
  - "plans/next-steps.md"
---

# Retrospective — Load chat sessions from JSONL logs

Written at merge time. This is a retrospective on **decisions and artifacts**, not on people.
Each entry records what we knew, what we assumed, and what we would check next time — so the
same class of bug is predictable rather than merely survivable.

## Evidence (measured, not remembered)

| Measure | Value |
|---|---|
| Diff at merge | **878 insertions / 58 deletions** across 4 files (330 `main.py`, 276 `test_main.py`, 181 `App.*`) |
| Of which tests | 276 lines (~43%) |
| `backend/main.py` size | **830 lines, 27 top-level definitions, 6 unrelated concerns** |
| Largest single function | `prepare_session` — **130 lines**, 4 concerns |
| Tests depending on runtime state | **1** (`test_prepare_session_on_real_log` → `../logs/371c7225….jsonl`, gitignored) |
| Session-log failure this feature fixed | **1** (`098ca653`, dangling `tool_calls` + cursor drift) |
| Mermaid blocks checked | 2 in `plans/feature-load-jsonl-sequence.md` — **both parse** (re-verified with `mermaid@10`) |

## What went well

1. **The structured workflow held.** `Requirements → Design/Plan → Implement → Review` produced
   artifacts that paid for themselves during the bug hunt: the sequence doc (`feature-load-jsonl-sequence.md`)
   described *exactly* what the log should contain, which is what made the missing `tool` message
   visible as a deviation rather than an unknown. The plan's per-step **Verify** commands meant
   "is Step 4 done?" was answerable from the code in minutes instead of by opinion.
2. **Write-ahead logging made a 100-turn-later bug debuggable.** The offending turn had failed long
   before the symptom appeared. Because every request/response was logged with a sequence number and
   timestamp, the failure point was found by replaying the file, not by reproducing the state.
3. **Pairing caught the real defect.** Review turned up a genuine ordering bug (string sorting on
   ISO timestamps with differing offsets) and a payload inconsistency I introduced while fixing it
   (`updated_at` dropped but still consumed by the UI). Neither was caught by tests alone.
4. **Tests caught my own regression.** The 5 new ordering tests pinned the offset case; without them
   the "fix" would have looked correct.
5. **The plan was treated as a contract, not a script.** When Step 4 appeared done but unticked, we
   verified against the spec rather than trusting appearance — and found the real gap was in Step 5.

## What didn't go well

1. **Missing guardrails — the dominant theme.**
   - I **started a live server on port 8077** from inside a tool call. That is a side effect the
     harness should make impossible (or require consent for), not something a human has to police.
   - Tests read **gitignored runtime artifacts** (`logs/*.jsonl`). On a fresh clone that test errors;
     deleting a session breaks it. A test that fails for reasons unrelated to the code is worse than
     no test, because it trains people to ignore red.
2. **A mega-function accumulated silently.** `prepare_session` grew to 130 lines and four concerns
   (record replay, log repair, turn grouping, UI projection) *without any single step being the
   culprit*. Each addition was locally reasonable; the total was not. Nothing in the plan or the
   tooling flags "this function now has four jobs."
3. **Stringly-typed boundaries.** Response shapes were plain `dict`s, so the UI's expectations and the
   backend's output were kept in sync by hand. The bug that started this session was, at root, a
   *shape* disagreement that nothing validated.
4. **The bug was fixed twice before it was fixed once.** My first two repair attempts were accepted
   by the local checks and rejected by the real API. Had I validated against the actual provider
   earlier, the loop would have been one iteration, not three.
5. **Branch hygiene is worse than it looks.** `feature/adding-jsonl-logs`,
   `feature/add-visualization-service-poc` and `feature/load-jsonl` **all point at the same commit**
   (`cf09518`) as `main`, each with 0 unique commits, and **all feature work is uncommitted**. There is
   no branch to merge from — "merge" currently means "commit in place on a branch that is main."

## More of that in the future

- **Structure first.** The workflow itself worked; keep it. The failure mode was not the process but
  the *absence of guardrails around it* — a process without enforcement degrades quietly.
- **Planned guardrails** (each becomes a follow-up feature, see `next-steps.md`):
  - tool calls may not start/stop long-lived servers — enforced by the harness, not by memory;
  - tests may not read gitignored runtime state — enforced by fixtures;
  - schema agreement between Pydantic and the UI — enforced by generated types + a CI diff check;
  - size/complexity budget per function — enforced by a linter, not by review attention.
- **Pydantic is the source of truth.** Confirmed preference: models in Pydantic → OpenAPI schema →
  generated TypeScript. Agreement is then *mechanical*; checking it is automatic.

## Decision archaeology

Each notable decision, and what would have surfaced it sooner.

| Decision | Consequence | Would have been caught by |
|---|---|---|
| Log the request **before** calling the model (WAL) | A failed call leaves a request with no `tool` results — unrunnable history | A schema/state-machine model where "tool_calls pending" is a first-class state, not a repair branch |
| `SessionLog` cursor counts messages written | Turn that dies mid-flight advances the cursor past real content; later user messages get sliced away | A test that kills a turn mid-loop (regression test now exists) |
| Response shapes as `dict` | UI/back-end agreement by convention; shape bugs surface only at the provider | Pydantic response models + generated TS |
| Keep `logs/` gitignored, test against it anyway | Non-reproducible test on a fresh clone | A fixtures directory; CI runs on a clean checkout |
| Verify with local unit checks | Two fixes accepted locally, rejected by the real API | One early smoke call against the provider |

## Self-correction note

The `mermaid` concern raised in review **did not reproduce**: both blocks in
`plans/feature-load-jsonl-sequence.md` parse cleanly under `mermaid@10`. Either it was fixed by an
earlier edit in this feature, or it lives on a branch — but both suspect branches
(`feature/adding-jsonl-logs`, `feature/add-visualization-service-poc`) are **empty** (0 commits ahead
of `main`), so there is nothing there to inspect. Recorded as **unreproduced**, with a validation
feature planned rather than a speculative fix.

## Actions

Deferred into ordered follow-up features; none is a merge blocker.

1. `isolate-test-fixtures` — remove the live-file test dependency (small, do first)
2. `typed-session-contract` — Pydantic source of truth → OpenAPI → generated UI types
3. `extract-session-state-machine` — split `main.py`; model tool-calling as explicit states
4. `harness-guardrails` — no server side effects; function size budget; lint/type gates
5. `document-sdlc` — write down the workflow that is currently implicit
   (**held**: premature until the guardrails above exist, or the doc describes an aspiration)
6. `mermaid-validation` — render every mermaid block in CI (**held**: no reproducible failure)
