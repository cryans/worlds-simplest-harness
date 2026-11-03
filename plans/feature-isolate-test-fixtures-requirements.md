---
branch: "isolate-test-fixtures"
feature: "isolate-test-fixtures"
status: "proposed"
references:
  - "plans/next-steps.md"
  - "plans/feature-load-jsonl-retro.md"
---

# Isolate test fixtures — requirements

**Goal.** Every test passes on a clean clone. No test reads gitignored or developer-machine state.

**Why now.** `test_prepare_session_on_real_log` reads gitignored `logs/371c7225….jsonl`. Hiding
`logs/` gives `assert 0 == 9` — **quietly**: `read_records` returns early on
`if not path.exists()` (main.py:294), so a missing file yields `{"turns": []}` and blames the
parser, not the fixtures.

## Requirements

1. **Frozen fixture.** Copy `371c7225…` (39 lines / 126 KB — not the 962 KB `098ca653…`) to
   `backend/tests/fixtures/`. Never regenerated or written by a test; `fixtures/README.md` says
   what it is and that it is frozen.
2. **Test reads only the fixture.** `_REAL_LOG` resolves via `Path(__file__).parent`, not
   `parent.parent / "logs"`. Keep the assertions (9 turns, no warnings, first user text, first step
   is a `bash` call with a result, no system message).
3. **Architectural assertion.** Probe the *effect*, never grep source text. An autouse fixture in
   `backend/tests/conftest.py` wraps pathlib's `Path.open`, `read_text`, `exists`, `resolve`,
   `glob` and fails reads outside an allow-list: that test's `tmp_path`, `tests/fixtures/`,
   stdlib/site-packages. Not the repo root. Wrapping `exists` is load-bearing. Assume pathlib-only;
   `os.path`/`os.listdir` go unwrapped. ~20 lines, failure names the path and test. Not the
   general auditor — that is `harness-guardrails` (#4).
4. **One test home.** Move `backend/test_main.py` to `backend/tests/`. Command:
   `uv run pytest -q`. No Makefile or Justfile.

## Out of scope
- `sample-project*/` — gitignored; `test_run_bash_stdout_and_working_directory` asserts `pwd`
  equals it. Ignored, and excluded from #3's allow-list.
- Any `main.py` behaviour change (e.g. `prepare_session` raising on a missing file) —
  `extract-session-state-machine`.
- `pyproject.toml`, `ruff`, `mypy`, `pytest.ini`, coverage, CI — `harness-guardrails` (#4).
- Rewriting tests, adding coverage, generating `logs/` from a seed.

## Acceptance criteria
4. `backend/test_main.py` gone; tests under `backend/tests/`.
5. Fixture unchanged after a full run (`git status --porcelain` clean).

"Green with no `logs/`" stays a manual review check — automating it needs a subprocess or a stashed
tree. #3 keeps it true afterwards.
