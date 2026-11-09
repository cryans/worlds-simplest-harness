"""Environment configuration and paths.

Importing this reads `backend/.env` (if present) but must not create directories.
Sandbox creation belongs to the tools/mode setup, not to importing this module.
"""

import os
from contextvars import ContextVar
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # reads backend/.env if it exists, so you don't have to export keys

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
MAX_STEPS = int(os.environ.get("MAX_STEPS", "100"))  # how many model<->tool round-trips
BASH_TIMEOUT = int(os.environ.get("BASH_TIMEOUT", "30"))  # seconds per bash command
MODEL_MAX_RETRIES = int(os.environ.get("MODEL_MAX_RETRIES", "2"))  # retries per model call

# The default sandbox folder. It lives at the repo ROOT, next to backend/ and frontend/.
# `config.py` sits at backend/src/wsh/, so three parents up is the repo root.
# This module deliberately does NOT create it.
SAMPLE_PROJECT = (Path(__file__).resolve().parents[3] / "sample-project").resolve()

# The active sandbox is session/task-scoped. `bash` reads this instead of the module
# global so a smoke session can point at a /tmp directory without affecting others.
_current_sandbox: ContextVar[Path] = ContextVar("wsh_current_sandbox", default=SAMPLE_PROJECT)


def set_current_sandbox(path: Path):
    """Set the current task's sandbox and return a reset token."""
    return _current_sandbox.set(path)


def get_current_sandbox() -> Path:
    """Return the sandbox that should be used for the current task/session."""
    return _current_sandbox.get()


def reset_current_sandbox(token) -> None:
    """Reset the current task's sandbox to the value before ``set_current_sandbox``."""
    _current_sandbox.reset(token)


# Session logs: one append-only JSONL file per session, at the repo ROOT.
LOGS_DIR = (Path(__file__).resolve().parents[3] / "logs").resolve()

SYSTEM_PROMPT_TEMPLATE = """
You are a helpful coding assistant with access to ONE tool: `bash`.

Rules:
- `bash` runs a single command inside the project folder ({sandbox}).
- Use it to inspect files, create files, edit them, and run them.
- You may use it several times. After each command you will see its output.
- When you are finished, reply to the user in plain text. Do NOT call bash again.

Think step by step, and keep commands short and focused.
""".strip()


def make_system_prompt(sandbox: Path = SAMPLE_PROJECT) -> str:
    """The system prompt for a specific sandbox path."""
    return SYSTEM_PROMPT_TEMPLATE.format(sandbox=sandbox)


# Backward-compatible default for callers that don't need a per-session prompt yet.
SYSTEM_PROMPT = make_system_prompt()
