"""Session-list metadata and ordering (datetimes, not strings)."""

import asyncio
import json
from datetime import datetime, timezone

import wsh.api.routes
from wsh.api.routes import list_sessions
from wsh.session import _parse_ts, _session_meta


def _write_log(tmp_path, name, stamps):
    """One session header + one response per stamp (all in file/seq order)."""
    recs = [{"seq": 0, "type": "session", "session": name, "ts": stamps[0] if stamps else None}]
    for i, ts in enumerate(stamps[1:], start=1):
        recs.append({"seq": i, "type": "response", "step": i, "total_messages": i,
                     "ts": ts, "message": {"role": "assistant", "content": "ok"}})
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return path


def test_parse_ts_is_timezone_aware_utc():
    # Same instant, written two ways: equal datetimes, unequal strings.
    a = _parse_ts("2026-11-02T15:06:36+00:00")
    b = _parse_ts("2026-11-02T16:06:36+01:00")
    assert a == b
    assert a.tzinfo is not None and a.utcoffset().total_seconds() == 0
    # A missing offset is treated as UTC rather than failing.
    assert _parse_ts("2026-11-02T15:06:36").tzinfo is not None
    assert _parse_ts("not a date") is None
    assert _parse_ts(None) is None


def test_list_sessions_sorts_on_datetime_not_string(tmp_path, monkeypatch):
    _write_log(tmp_path, "later", ["2026-11-02T15:30:00+00:00", "2026-11-02T15:30:00+00:00"])
    _write_log(tmp_path, "earlier", ["2026-11-02T16:06:00+01:00", "2026-11-02T16:06:00+01:00"])
    monkeypatch.setattr(wsh.api.routes, "LOGS_DIR", tmp_path)
    body = asyncio.run(list_sessions())
    assert [s["id"] for s in body["sessions"]] == ["later", "earlier"]


def test_list_sessions_newest_first_uses_latest_record(tmp_path, monkeypatch):
    _write_log(tmp_path, "old", ["2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00"])
    _write_log(tmp_path, "new", ["2026-01-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00"])
    monkeypatch.setattr(wsh.api.routes, "LOGS_DIR", tmp_path)
    body = asyncio.run(list_sessions())
    assert [s["id"] for s in body["sessions"]] == ["new", "old"]


def test_list_sessions_header_only_falls_back_to_mtime(tmp_path, monkeypatch):
    path = _write_log(tmp_path, "bare", [])
    monkeypatch.setattr(wsh.api.routes, "LOGS_DIR", tmp_path)
    meta = asyncio.run(list_sessions())["sessions"][0]
    assert meta["id"] == "bare"
    assert meta["updated"] == datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc)


def test_session_meta_has_no_string_sorted_fields(tmp_path):
    path = _write_log(tmp_path, "s1", ["2026-01-01T00:00:00+00:00"])
    meta = _session_meta(path)
    assert "modified_at" not in meta          # ambiguous, dropped
    assert isinstance(meta["updated"], datetime)
    assert isinstance(meta["created"], datetime)
