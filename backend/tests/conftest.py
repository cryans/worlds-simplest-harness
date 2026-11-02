"""Test harness: make `backend/` importable, and forbid reading files we do not own.

pytest inserts the rootdir of the first collected test into sys.path; once that
test lives in `tests/`, `backend/` is no longer on the path. Adding it here keeps
`import main` working from the new location.
"""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


# --- the "no ambient state" guard -------------------------------------------
#
# Tests may read only: the frozen fixtures, this test's tmp_path, the temp root
# (pytest's own cleanup reaches /tmp/pytest-of-<user>), and the interpreter/
# stdlib/site-packages trees. Anything else -- ../logs, an absolute developer
# path, ~/.config -- is recorded and fails the test at teardown, naming the path.
#
# Violations are COLLECTED, not raised on sight. Raising from inside a wrapped
# pathlib method aborts pytest itself mid-report (traceback formatting re-reads
# source files), turning a clear failure into an INTERNALERROR. Collecting also
# keeps one bad read from masking the real assertion error.
#
# We wrap pathlib, not os.path: fs access in this codebase goes through pathlib,
# and wrapping os.path catches more in false positives than it does in bugs.
# Assume pathlib-only; os.path/os.listdir are unwrapped by design.

import sysconfig  # noqa: E402
import tempfile  # noqa: E402

import pytest  # noqa: E402

FIXTURES = (Path(__file__).resolve().parent / "fixtures").resolve()
_STDLIB = Path(sysconfig.get_paths()["stdlib"]).resolve()
_PURELIB = Path(sysconfig.get_paths()["purelib"]).resolve()
_TEMP_ROOT = Path(tempfile.gettempdir()).resolve()

_GUARDED = ("open", "read_text", "read_bytes", "exists", "is_file", "is_dir", "glob")

# Capture before monkeypatching so _allowed() does not recurse into its wrapper.
_real_resolve = Path.resolve


def _allowed(path: Path, tmp: Path) -> bool:
    try:
        p = _real_resolve(path)
    except (OSError, RuntimeError):
        return True  # unresolvable: not a read we can judge
    if any(p == r or r in p.parents for r in (_STDLIB, _PURELIB, tmp, FIXTURES, _TEMP_ROOT)):
        return True
    # pytest's own machinery: its cache, and the sources it formats tracebacks from.
    if any(part in ("__pycache__", ".pytest_cache") for part in p.parts):
        return True
    if p.suffix == ".py" and str(p).startswith(str(BACKEND)):
        return True
    return False


@pytest.fixture(autouse=True)
def no_ambient_reads(request, monkeypatch):
    tmp = Path(request.getfixturevalue("tmp_path")).resolve()
    violations: list[Path] = []

    def wrap(name):
        original = getattr(Path, name)

        def guarded(self, *args, **kwargs):
            if not _allowed(Path(self), tmp) and Path(self) not in violations:
                violations.append(Path(self))
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, name, guarded, raising=True)

    for name in _GUARDED:
        wrap(name)

    yield

    if violations:
        listed = "\n  ".join(str(v) for v in violations)
        pytest.fail(
            f"{request.node.nodeid} read state outside tmp_path/fixtures/stdlib:\n  {listed}\n"
            "Tests must not touch ambient or gitignored paths; commit a fixture instead.",
            pytrace=False,
        )
