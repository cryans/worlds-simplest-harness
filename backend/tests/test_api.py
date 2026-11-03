"""The read-only endpoints and the session-id sanitizer."""

import json

from fastapi.testclient import TestClient

import wsh.api.routes
from wsh.api.app import app
from wsh.api.routes import is_safe_session_id


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _base_records():
    hdr = {"seq": 0, "ts": "2026-01-01T00:00:00+00:00", "session": "s1", "type": "session",
           "model": "m"}
    req = {"seq": 1, "ts": "2026-01-01T00:00:01+00:00", "session": "s1", "type": "request",
           "step": 1, "delta": [{"role": "user", "content": "hi"}], "total_messages": 1}
    res = {"seq": 2, "ts": "2026-01-01T00:00:02+00:00", "session": "s1", "type": "response",
           "step": 1, "message": {"role": "assistant", "content": "hello"}, "total_messages": 2}
    return [hdr, req, res]


def test_session_id_sanitizer():
    assert is_safe_session_id("abc-123-ABC")
    assert not is_safe_session_id("")
    assert not is_safe_session_id("../../etc/passwd")
    assert not is_safe_session_id("a b")


def test_list_sessions_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(wsh.api.routes, "LOGS_DIR", tmp_path)
    _write_jsonl(tmp_path / "aaaaa.jsonl", _base_records())
    _write_jsonl(tmp_path / "bbbbb.jsonl", _base_records())
    _write_jsonl(tmp_path / "empty.jsonl", [])  # should be hidden
    body = TestClient(app).get("/api/sessions").json()
    ids = [s["id"] for s in body["sessions"]]
    assert len(ids) == 2                 # the two non-empty files
    assert "empty" not in ids            # empty file hidden
    assert all(s["messages"] > 0 for s in body["sessions"])


def test_get_session_endpoint_404s(tmp_path, monkeypatch):
    monkeypatch.setattr(wsh.api.routes, "LOGS_DIR", tmp_path)
    _write_jsonl(tmp_path / "good.jsonl", _base_records())
    c = TestClient(app)
    assert c.get("/api/sessions/good").status_code == 200
    assert c.get("/api/sessions/nope").status_code == 404
    assert c.get("/api/sessions/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_health_endpoint():
    body = TestClient(app).get("/api/health").json()
    assert body["ok"] is True
    assert "model" in body
    assert "has_key" in body
