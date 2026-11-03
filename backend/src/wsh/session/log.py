"""Append-only, write-ahead JSONL log for one session."""

import json
from datetime import datetime, timezone
from pathlib import Path

from wsh.config import LOGS_DIR


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string (with timezone)."""
    return datetime.now(timezone.utc).isoformat()


class SessionLog:
    """Append-only, write-ahead JSONL log for one session.

    One JSON object per line. Every line is an immutable event with a
    monotonically-increasing ``seq`` (the WAL sequence number), a UTC ``ts``,
    the ``session`` id, and a ``type``. Replaying the file in order
    reconstructs exactly what went to the model — without ever re-serialising
    the whole history: each ``request`` line carries only the NEW messages
    since the previous one (its *delta*), never ``[m1]``, ``[m1, m2]``, …
    """

    def __init__(self, session_id: str, logs_dir: Path = LOGS_DIR):
        self.session_id = session_id
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.path = logs_dir / f"{session_id}.jsonl"
        self._seq, self._logged = self._resume()

    def _resume(self) -> tuple[int, int]:
        """Scan an existing file to continue where it left off.

        Returns ``(next_seq, logged_messages)``. ``logged_messages`` is the
        highest ``total_messages`` already written, so a history replayed by
        the browser is never logged twice. Torn/partial trailing lines are
        ignored (they are the cost of a crash mid-append, which we don't try
        to repair).
        """
        next_seq = 0
        logged = 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                next_seq = max(next_seq, int(rec.get("seq", -1)) + 1)
                logged = max(logged, int(rec.get("total_messages", 0) or 0))
        return next_seq, logged

    def _append(self, record: dict) -> None:
        """Stamp the envelope and append one line. Never rewrites earlier lines."""
        record["seq"] = self._seq
        record["ts"] = now_iso()
        record["session"] = self.session_id
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        self._seq += 1

    def write_session(self, model, base_url, sandbox, config, system_prompt, tools) -> None:
        """The one-time header: static config, so it isn't repeated per request."""
        if self._seq != 0:  # header already written for an existing file
            return
        self._append(
            {
                "type": "session",
                "model": model,
                "base_url": base_url,
                "sandbox": sandbox,
                "config": config,
                "system_prompt": system_prompt,
                "tools": tools,
            }
        )

    def write_request(self, convo: list[dict], step: int, model: str) -> None:
        """Log the model request. ``convo`` has the system message at [0]; the
        delta is only the conversation messages added since the last request."""
        msgs = convo[1:]  # the system message is captured in the header
        # `_logged` is the number of messages the *file* says are already known.
        # A failed/aborted turn changes the conversation without the matching
        # messages ever reaching the file, so trust the client's history as the
        # source of truth whenever it disagrees: replay stays aligned with what
        # the next request actually sends.
        if len(msgs) < self._logged:
            self._logged = len(msgs)
        delta = msgs[self._logged :]
        self._logged = len(msgs)
        self._append(
            {
                "type": "request",
                "step": step,
                "model": model,
                "delta": delta,
                "total_messages": len(msgs),
            }
        )

    def write_response(self, message, step, model, latency_ms, finish_reason, usage) -> None:
        """Log the model's reply (also counts as one more logged message)."""
        self._logged += 1
        self._append(
            {
                "type": "response",
                "step": step,
                "model": model,
                "latency_ms": latency_ms,
                "finish_reason": finish_reason,
                "message": message,
                "usage": usage,
                "total_messages": self._logged,
            }
        )

    def write_error(self, message: str, step: int) -> None:
        """Log a failed model call (its request line is already on disk)."""
        self._append({"type": "error", "step": step, "message": message})
