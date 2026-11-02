# Test fixtures

Frozen inputs. **Never regenerate, never append, never write.** A test that mutates a fixture
turns "the parser changed" into "the fixture changed", which is the bug this directory exists to
prevent.

## `371c7225-5c73-436a-81b8-70db500c92db.jsonl`

A real session log, copied verbatim from `logs/` (gitignored) on 2026-11-02. 39 lines, one header
plus nine Q&A turns, including `bash` tool calls with results.

It is used by `test_prepare_session_on_real_log`, which asserts the exact turn count and the
shape of the first step. Those assertions are the point: they catch `prepare_session` silently
returning zero turns, which is what happens when the file is missing — `read_records` returns
early on `if not path.exists()` rather than raising.

Chosen over `098ca653…` (962 KB) because it exercises the same paths at 126 KB.
