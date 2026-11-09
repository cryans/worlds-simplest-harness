"""agent_loop: retry on transient model failures and typed, never-empty error messages."""

import asyncio
import json

import httpx

import wsh.agent.loop as loop
from wsh.agent.loop import agent_loop
from wsh.session import SessionLog


def _request():
    return httpx.Request("POST", "http://example.com/chat/completions")


def _response(content):
    return {"choices": [{"message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}], "usage": {}}


def _status_error(status_code, text=""):
    request = _request()
    response = httpx.Response(status_code, request=request, text=text)
    return httpx.HTTPStatusError(f"{status_code}", request=request, response=response)


def _collect(messages, log):
    async def run():
        return [e async for e in agent_loop(messages, log)]
    return asyncio.run(run())


def _parse(blocks):
    """Turn yielded SseEvent models into (event_name, payload_dict) pairs.

    ``blocks`` is the list returned by ``_collect``: each item is now a Pydantic
    model, not an encoded SSE string. ``event`` is ``model.type``; ``data`` is the
    model's own fields (minus ``type``, which the tests assert via ``event``).
    """
    out = []
    for model in blocks:
        data = {k: v for k, v in model.model_dump().items() if k != "type"}
        out.append((model.type, data))
    return out


def _log_types(tmp_path):
    lines = (tmp_path / "s1.jsonl").read_text().splitlines()
    return [json.loads(line)["type"] for line in lines if line.strip()]


def _messages():
    return [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


def test_retries_on_503_then_succeeds(tmp_path, monkeypatch):
    calls = {"n": 0}

    async def fake(convo):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _status_error(503, "overloaded")
        return _response("hello")

    monkeypatch.setattr(loop, "call_model", fake)
    monkeypatch.setattr(loop, "RETRY_BACKOFF_S", 0)

    log = SessionLog("s1", logs_dir=tmp_path)
    blocks = _parse(_collect(_messages(), log))

    assert calls["n"] == 2
    assert any(e == "answer" for e, _ in blocks)
    assert any(e == "status" and d["text"].startswith("retrying") for e, d in blocks)
    assert _log_types(tmp_path) == ["request", "response"]


def test_retries_on_connection_error_then_succeeds(tmp_path, monkeypatch):
    calls = {"n": 0}

    async def fake(convo):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused")
        return _response("ok")

    monkeypatch.setattr(loop, "call_model", fake)
    monkeypatch.setattr(loop, "RETRY_BACKOFF_S", 0)

    log = SessionLog("s1", logs_dir=tmp_path)
    blocks = _parse(_collect(_messages(), log))

    assert calls["n"] == 2
    assert any(e == "answer" for e, _ in blocks)


def test_503_exhaustion_yields_typed_error(tmp_path, monkeypatch):
    async def fake(convo):
        raise _status_error(503, "overloaded")

    monkeypatch.setattr(loop, "call_model", fake)
    monkeypatch.setattr(loop, "RETRY_BACKOFF_S", 0)

    log = SessionLog("s1", logs_dir=tmp_path)
    blocks = _parse(_collect(_messages(), log))

    errors = [d for e, d in blocks if e == "error"]
    assert len(errors) == 1
    assert "HTTPStatusError" in errors[0]["message"]
    assert errors[0]["message"].strip()
    retries = [d for e, d in blocks if e == "status" and d["text"].startswith("retrying")]
    assert len(retries) == loop.MODEL_MAX_RETRIES


def test_empty_connection_error_message_names_type_and_is_never_empty(tmp_path, monkeypatch):
    async def fake(convo):
        raise httpx.ConnectError("")  # str(e) == ""

    monkeypatch.setattr(loop, "call_model", fake)
    monkeypatch.setattr(loop, "RETRY_BACKOFF_S", 0)

    log = SessionLog("s1", logs_dir=tmp_path)
    blocks = _parse(_collect(_messages(), log))

    errors = [d for e, d in blocks if e == "error"]
    assert len(errors) == 1
    assert "ConnectError" in errors[0]["message"]
    assert "no detail" in errors[0]["message"]
    assert errors[0]["message"].strip()


def test_4xx_fails_immediately_no_retry(tmp_path, monkeypatch):
    calls = {"n": 0}

    async def fake(convo):
        calls["n"] += 1
        raise _status_error(401, "bad key")

    monkeypatch.setattr(loop, "call_model", fake)
    monkeypatch.setattr(loop, "RETRY_BACKOFF_S", 0)

    log = SessionLog("s1", logs_dir=tmp_path)
    blocks = _parse(_collect(_messages(), log))

    assert calls["n"] == 1
    errors = [d for e, d in blocks if e == "error"]
    assert len(errors) == 1
    assert "HTTPStatusError" in errors[0]["message"]
    assert "401" in errors[0]["message"]
    retries = [d for e, d in blocks if e == "status" and d["text"].startswith("retrying")]
    assert retries == []
