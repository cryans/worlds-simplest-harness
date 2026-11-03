"""Cheap, derived metadata for the session list."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wsh.session.replay import read_records


# Timestamps in a log are ISO-8601 with an offset (``...T15:06:36+00:00``).
# Compare them as datetimes, never as strings: two equal-looking strings can
# carry different offsets, and naive-vs-aware comparison would raise anyway.


def _parse_ts(value: Any) -> datetime | None:
    """Parse one log timestamp into an aware UTC datetime (None if unusable)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:  # treat a missing offset as UTC, as the log intends
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _updated_at(records: list[dict], path: Path) -> datetime:
    """When the session last did anything: newest record, else file mtime.

    The mtime fallback covers a header-only log (one write, no records with a
    ``ts`` we can read) so such a session still sorts sensibly instead of
    being pinned to the epoch. ``st_mtime`` is already real system time.
    """
    stamps = [ts for ts in (_parse_ts(r.get("ts")) for r in records) if ts is not None]
    if stamps:
        return max(stamps)
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _session_meta(path: Path) -> dict | None:
    """Cheap metadata for the session list, or None for an empty/unusable file."""
    records, _ = read_records(path)
    if not records:
        return None
    user_turns = sum(
        1
        for rec in records
        if rec.get("type") == "request"
        for m in (rec.get("delta") or [])
        if isinstance(m, dict) and m.get("role") == "user"
    )
    preview = ""
    for rec in records:
        if rec.get("type") == "request":
            for m in rec.get("delta") or []:
                if isinstance(m, dict) and m.get("role") == "user":
                    preview = (m.get("content") or "")[:120]
                    break
            if preview:
                break
    parent = records[0] if records else {}
    updated = _updated_at(records, path)
    return {
        "id": parent.get("session") or path.stem,
        # `created`/`updated` are real datetimes: the server sorts on them, so
        # ordering never depends on comparing strings or on every timestamp
        # sharing one UTC offset. `updated_at` is the same instant rendered for
        # the UI label (ISO-8601 UTC); clients must not sort on it.
        "created": _parse_ts(parent.get("ts")),
        "updated": updated,
        "created_at": parent.get("ts"),
        "updated_at": updated.isoformat(),
        "user_turns": user_turns,
        "messages": max((int(r.get("total_messages", 0) or 0) for r in records), default=0),
        "preview": preview,
    }
