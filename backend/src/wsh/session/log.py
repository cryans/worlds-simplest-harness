"""Append-only, write-ahead JSONL log for one session."""

import json
from datetime import datetime, timezone
from pathlib import Path

from wsh.config import LOGS_DIR, SAMPLE_PROJECT


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

    def __init__(
        self,
        session_id: str,
        logs_dir: Path = LOGS_DIR,
        sandbox: Path | None = None,
        mode: str = "normal",
    ):
        self.session_id = session_id
        self.sandbox = Path(sandbox) if sandbox is not None else SAMPLE_PROJECT
        self.mode = mode
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.path = logs_dir / f"{session_id}.jsonl"
        self._seq, self._logged, self._step = self._resume()

    def _resume(self) -> tuple[int, int]:
        """Scan an existing file to continue where it left off.

        Returns ``(next_seq, logged_messages, next_step)``. ``logged_messages``
        is the number of conversation messages the file has already recorded, so
        a history replayed by the browser is never logged twice. ``next_step``
        is the next round-trip number (``max(step)+1``), so steps never reset
        between turns. Torn/partial trailing lines are ignored (they are the
        cost of a crash mid-append, which we don't try to repair).

        ``logged`` is the *count* of messages recorded via ``request`` deltas
        (``len(delta)`` each) plus one per ``response`` — not the stored
        ``total_messages`` field. The stored field can drift after an aborted
        turn (a ``response`` records its count *before* the loop appends the
        following ``tool`` results), so trusting it makes ``write_request``
        re-emit already-known messages as new deltas, which corrupts the wire
        history with duplicate ``tool``/``assistant`` messages.
        """
        next_seq = 0
        logged = 0
        step = 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rtype = rec.get("type")
                if rtype in ("session", "sandbox") and rec.get("sandbox"):
                    self.sandbox = Path(rec["sandbox"])
                if rec.get("mode"):
                    self.mode = rec["mode"]
                next_seq = max(next_seq, int(rec.get("seq", -1)) + 1)
                if rtype == "request":
                    logged += len(rec.get("delta") or [])
                elif rtype == "response":
                    logged += 1
                step = max(step, int(rec.get("step", 0) or 0))
        return next_seq, logged, step + 1

    def next_step(self) -> int:
        """The next round-trip number for this session, then increment.

        The loop calls this once per model round-trip so the ``step`` written to
        every request/response/error line is monotonic across the whole session —
        Turn 2's first step continues from Turn 1's last, instead of resetting.
        """
        step = self._step
        self._step += 1
        return step

    def _append(self, record: dict) -> None:
        """Stamp the envelope and append one line. Never rewrites earlier lines."""
        record["seq"] = self._seq
        record["ts"] = now_iso()
        record["session"] = self.session_id
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        self._seq += 1

    def write_session(
        self, model, base_url, sandbox, config, system_prompt, tools, mode="normal"
    ) -> None:
        """The one-time header: static config, so it isn't repeated per request."""
        if self._seq != 0:  # header already written for an existing file
            return
        self._append(
            {
                "type": "session",
                "model": model,
                "base_url": base_url,
                "sandbox": sandbox,
                "mode": mode,
                "config": config,
                "system_prompt": system_prompt,
                "tools": tools,
            }
        )

    def write_mode(self, mode: str) -> None:
        """Append a mode override for this session (e.g. smoke -> normal)."""
        self._append({"type": "mode", "mode": mode})

    def write_sandbox(self, sandbox: Path) -> None:
        """Append a sandbox override for this session.

        The header records the sandbox at session start; a smoke session can later
        be switched back to the normal sandbox without rewriting history. Replay
        reads the latest ``sandbox`` record as the active sandbox.
        """
        self._append({"type": "sandbox", "sandbox": str(sandbox)})

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
