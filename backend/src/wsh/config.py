"""Environment configuration and paths — the only side-effectful module in `wsh`.

Importing this reads `backend/.env` (if present) and creates `sample-project/` at the
repo root. Keep every side effect here so the rest of the package stays import-safe.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # reads backend/.env if it exists, so you don't have to export keys

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
MAX_STEPS = int(os.environ.get("MAX_STEPS", "100"))  # how many model<->tool round-trips
BASH_TIMEOUT = int(os.environ.get("BASH_TIMEOUT", "30"))  # seconds per bash command

# The sandbox folder. It lives at the repo ROOT, next to backend/ and frontend/.
# `config.py` sits at backend/src/wsh/, so three parents up is the repo root.
SAMPLE_PROJECT = (Path(__file__).resolve().parents[3] / "sample-project").resolve()
SAMPLE_PROJECT.mkdir(exist_ok=True)

# Session logs: one append-only JSONL file per session, at the repo ROOT.
LOGS_DIR = (Path(__file__).resolve().parents[3] / "logs").resolve()

SYSTEM_PROMPT = f"""
You are a helpful coding assistant with access to ONE tool: `bash`.

Rules:
- `bash` runs a single command inside the project folder ({SAMPLE_PROJECT}).
- Use it to inspect files, create files, edit them, and run them.
- You may use it several times. After each command you will see its output.
- When you are finished, reply to the user in plain text. Do NOT call bash again.

Think step by step, and keep commands short and focused.
""".strip()
