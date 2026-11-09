"""The read-only endpoints and the session-id sanitizer."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

import wsh.api.routes
from wsh.api.app import app
from wsh.config import SAMPLE_PROJECT
from wsh.api.routes import (
    _is_smoke_command,
    _is_smoke_off_command,
    _new_smoke_sandbox,
    _replace_smoke_command,
    _replace_smoke_off_command,
    is_safe_session_id,
)
from wsh.models import AnswerEvent


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


def test_smoke_command_helpers():
    assert _is_smoke_command([{"role": "user", "content": "@sample-project"}])
    assert _is_smoke_command([{"role": "user", "content": "@sample-project do the thing"}])
    assert not _is_smoke_command([{"role": "user", "content": "hello"}])
    assert not _is_smoke_command([{"role": "user", "content": "@sample-projectx"}])

    assert _is_smoke_off_command([{"role": "user", "content": "@sample-project off"}])
    assert not _is_smoke_off_command([{"role": "user", "content": "@sample-project"}])

    out = _replace_smoke_command([{"role": "user", "content": "@sample-project"}], Path("/tmp/s"))
    assert "@sample-project" not in out[0]["content"]
    assert "/tmp/s" in out[0]["content"]

    out = _replace_smoke_command(
        [{"role": "user", "content": "@sample-project do the thing"}], Path("/tmp/s")
    )
    assert "First task: do the thing" in out[0]["content"]

    out = _replace_smoke_off_command([{"role": "user", "content": "@sample-project off"}])
    assert "@sample-project" not in out[0]["content"]
    assert "Smoke mode disabled" in out[0]["content"]


def _read_header(logs_dir):
    path = next(logs_dir.glob("*.jsonl"))
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return records[0]


def test_chat_smoke_command_uses_ephemeral_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(wsh.api.routes, "API_KEY", "x")
    monkeypatch.setattr(wsh.api.routes, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(wsh.api.routes, "_new_smoke_sandbox", lambda session_id: str(tmp_path / "smoke"))

    seen = {}

    async def fake_agent_loop(messages, log):
        seen["messages"] = messages
        seen["sandbox"] = log.sandbox
        yield AnswerEvent(
            type="answer",
            session_id=log.session_id,
            content="ok",
            messages=messages[1:],
        )

    monkeypatch.setattr(wsh.api.routes, "agent_loop", fake_agent_loop)

    resp = TestClient(app).post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "@sample-project"}]},
    )
    assert resp.status_code == 200

    header = _read_header(tmp_path)
    assert header["type"] == "session"
    assert header["sandbox"] == str(tmp_path / "smoke")
    assert seen["sandbox"] == tmp_path / "smoke"
    assert "@sample-project" not in json.dumps(seen["messages"])
    assert "Smoke mode enabled" in json.dumps(seen["messages"])
    assert str(tmp_path / "smoke") in seen["messages"][0]["content"]


def test_chat_normal_session_uses_default_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(wsh.api.routes, "API_KEY", "x")
    monkeypatch.setattr(wsh.api.routes, "LOGS_DIR", tmp_path)

    seen = {}

    async def fake_agent_loop(messages, log):
        seen["sandbox"] = log.sandbox
        seen["messages"] = messages
        yield AnswerEvent(
            type="answer",
            session_id=log.session_id,
            content="ok",
            messages=messages[1:],
        )

    monkeypatch.setattr(wsh.api.routes, "agent_loop", fake_agent_loop)

    resp = TestClient(app).post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert resp.status_code == 200

    header = _read_header(tmp_path)
    assert header["sandbox"] == str(SAMPLE_PROJECT)
    assert seen["sandbox"] == SAMPLE_PROJECT


def test_chat_smoke_off_restores_default_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(wsh.api.routes, "API_KEY", "x")
    monkeypatch.setattr(wsh.api.routes, "LOGS_DIR", tmp_path)

    header = {
        "seq": 0,
        "ts": "2026-01-01T00:00:00+00:00",
        "session": "s1",
        "type": "session",
        "model": "m",
        "sandbox": str(tmp_path / "smoke"),
    }
    (tmp_path / "s1.jsonl").write_text(json.dumps(header) + "\n", encoding="utf-8")

    seen = {}

    async def fake_agent_loop(messages, log):
        seen["messages"] = messages
        seen["sandbox"] = log.sandbox
        yield AnswerEvent(
            type="answer",
            session_id=log.session_id,
            content="ok",
            messages=messages[1:],
        )

    monkeypatch.setattr(wsh.api.routes, "agent_loop", fake_agent_loop)

    resp = TestClient(app).post(
        "/api/chat",
        json={
            "session_id": "s1",
            "messages": [{"role": "user", "content": "@sample-project off"}],
        },
    )
    assert resp.status_code == 200

    records = [
        json.loads(line)
        for line in (tmp_path / "s1.jsonl").read_text().splitlines()
        if line.strip()
    ]
    sandbox_records = [r for r in records if r.get("type") == "sandbox"]
    assert sandbox_records
    assert sandbox_records[-1]["sandbox"] == str(SAMPLE_PROJECT)
    assert seen["sandbox"] == SAMPLE_PROJECT
    assert "@sample-project" not in json.dumps(seen["messages"])
    assert "Smoke mode disabled" in json.dumps(seen["messages"])
