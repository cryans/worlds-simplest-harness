---
branch: "isolate-test-fixtures"
references:
  - "plans/feature-isolate-test-fixtures-requirements.md"
---

# Isolate test fixtures — implementation plan

Branch: `isolate-test-fixtures`. Requirements: `feature-isolate-test-fixtures-requirements.md`.

Tick each box only once its **Verify** passes; don't start the next step until it does.

## 1. Move the suite to `backend/tests/`
- [x] `mkdir backend/tests && git mv backend/test_main.py backend/tests/test_main.py`

Nothing else may change in this step. Doing the move first means every later `Verify` runs against
the final layout, so we never verify a path that is about to disappear.

**Verify:** `cd backend && uv run pytest -q` → 32 passed (unchanged), and
`ls backend/test_main.py` fails.

## 2. Commit the frozen fixture
- [x] `cp logs/371c7225-….jsonl backend/tests/fixtures/371c7225-….jsonl`
- [x] `backend/tests/fixtures/README.md`: what it is, where it came from, **frozen** — never
      regenerate, never append, never let a test write it.

**Verify:** `git status --porcelain backend/tests/fixtures` shows the fixture as untracked-to-add,
`wc -l` says 39, and the file is not matched by any `.gitignore` rule
(`git check-ignore -v backend/tests/fixtures/*.jsonl` exits 1).

## 3. Point the real-log test at the fixture
- [x] In `backend/tests/test_main.py`: `_REAL_LOG = Path(__file__).parent / "fixtures" / "….jsonl"`.
- [x] Leave the assertions alone (9 turns, `warnings == []`, first user text, first step `bash`
      with a result, no system message in `messages`).

**Verify:** `cd backend && uv run pytest -q` → 32 passed. Then the real proof:
`mv logs /tmp/logs_hidden && uv run pytest -q; mv /tmp/logs_hidden logs` → 32 passed **with no
`logs/` directory**. (This is the one-time manual check; see requirements' acceptance criteria.)

## 4. Add the filesystem auditor
- [x] `backend/tests/conftest.py`: autouse fixture wrapping pathlib `Path.open`, `read_text`,
      `exists`, `resolve`, `glob`.
- [x] Allow-list, built from `sysconfig.get_paths()['stdlib']` and `['purelib']`, plus each test's
      `tmp_path` and `backend/tests/fixtures/`. Not the repo root.
- [x] Failure message names the offending path and the test.

Wrapping `exists` is load-bearing: `read_records` returns early on `if not path.exists()` (main.py:294),
so an `open`-only wrapper would not catch the very bug this feature exists to fix.

**Verify:** `uv run pytest -q` → 32 passed (the guard must be silent on a clean suite), and a
deliberately-broken scratch test — reading `../logs/<any>.jsonl` — fails naming that path. Delete
the scratch test.

## 5. Prove the guard actually bites
- [x] Temporarily revert `_REAL_LOG` to `parent.parent / "logs" / …`, run, confirm the auditor fails
      with a message naming the `logs/` path (not `assert 0 == 9`), then revert.

This is the step that distinguishes a guard from decoration. Without it, step 4's "32 passed" proves
only that the wrapper is installed, not that it catches anything.

**Verify:** the failing run's message names the path; after reverting, `uv run pytest -q` → 32 passed.

## Notes from implementation (deltas from the plan as written)

- **Step 1 needed a `conftest.py` to pass.** Moving `test_main.py` into `tests/` broke `import main`
  (pytest inserts the *collected test's* rootdir, which became `tests/`). The same move also broke
  `_REAL_LOG`, because it used `parent.parent` — a live demonstration of the bug. Both were expected
  transitions, fixed by step 3 + the `sys.path` insert.
- **Step 4's first shape was wrong, and step 5 is what caught it.** A naive `raise` inside the
  monkeypatched pathlib methods fired on *pytest's own* I/O — `.pytest_cache`, traceback source
  formatting, `main.py` itself — producing `INTERNALERROR` and masking the real error. Rewritten to
  **collect** violations and `pytest.fail(..., pytrace=False)` at teardown, which names every
  offending path once, cleanly.
- Allow-list grew by two entries that only showed up at runtime: the temp root (pytest's
  `cleanup_numbered_dir` reaches `/tmp/pytest-of-<user>`) and `.py` files under `backend/` (traceback
  formatting reads source). Without these the guard is unusable.
- `exists`/`is_file`/`is_dir`/`glob` are wrapped; `resolve` is wrapped for the *check* but
  `_allowed()` uses the captured real `Path.resolve` to avoid self-recursion.

## Done when
The suite passes with `logs/` absent · `_REAL_LOG` reads only the committed fixture · the auditor
fails a test that reaches outside `tmp_path`/`fixtures/`/stdlib/site-packages · `backend/test_main.py`
is gone · the fixture is byte-identical after a full run (`git status --porcelain` clean).
