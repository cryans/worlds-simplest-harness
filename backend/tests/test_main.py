"""Tests for the @tool decorator, registry, and the pieces it wires together.

Run from backend/ with:
    .venv/bin/python -m pytest -q
"""

import asyncio
import json

import main


# --- the @tool decorator + registry -----------------------------------------

def test_bash_is_registered():
    assert "bash" in main.TOOL_REGISTRY


def test_bash_schema_is_generated():
    entry = next(t for t in main.TOOLS if t["function"]["name"] == "bash")
    fn = entry["function"]
    params = fn["parameters"]

    assert entry["type"] == "function"
    assert fn["name"] == "bash"
    assert "Run a bash command" in fn["description"]

    # The schema we used to hand-write, now produced from `command: str`.
    assert params["type"] == "object"
    assert params["properties"]["command"]["type"] == "string"
    assert params["required"] == ["command"]


def test_decorator_registers_custom_tool():
    @main.tool
    async def add(a: int, b: int = 0) -> int:
        """Add two numbers."""
        return a + b

    try:
        assert main.TOOL_REGISTRY["add"] is add

        entry = next(t for t in main.TOOLS if t["function"]["name"] == "add")
        params = entry["function"]["parameters"]

        assert entry["function"]["description"] == "Add two numbers."
        assert params["properties"]["a"]["type"] == "integer"
        assert params["properties"]["b"]["type"] == "integer"
        # b has a default, so only a is required.
        assert params["required"] == ["a"]
    finally:
        # Leave the global state clean for the other tests.
        main.TOOL_REGISTRY.pop("add", None)
        main.TOOLS[:] = [t for t in main.TOOLS if t["function"]["name"] != "add"]


# --- call_tool: sync and async ----------------------------------------------

def test_call_tool_with_sync_function():
    def double(x: int) -> int:
        return x * 2

    assert asyncio.run(main.call_tool(double, {"x": 21})) == 42


def test_call_tool_with_async_function():
    async def triple(x: int) -> int:
        return x * 3

    assert asyncio.run(main.call_tool(triple, {"x": 14})) == 42


# --- run_bash: the actual tool ----------------------------------------------

def test_run_bash_stdout_and_working_directory():
    result = asyncio.run(main.run_bash("pwd && echo hello"))

    assert result["exit_code"] == 0
    assert str(main.SAMPLE_PROJECT) in result["stdout"]  # runs in the sandbox
    assert result["stdout"].strip().splitlines()[-1] == "hello"


def test_run_bash_reports_exit_code():
    result = asyncio.run(main.run_bash("exit 3"))
    assert result["exit_code"] == 3


def test_run_bash_times_out(monkeypatch):
    monkeypatch.setattr(main, "BASH_TIMEOUT", 1)
    result = asyncio.run(main.run_bash("sleep 3"))

    assert result["exit_code"] is None
    assert "timed out" in result["stderr"]


# --- SessionLog: append-only, write-ahead, delta (not cumulative) ------------

def _read_log(tmp_path, session_id):
    return [
        json.loads(line)
        for line in (tmp_path / f"{session_id}.jsonl").read_text().splitlines()
        if line.strip()
    ]


def test_session_log_writes_deltas_not_cumulative_history(tmp_path):
    log = main.SessionLog("delta-test", logs_dir=tmp_path)
    log.write_session("m", "http://x", "/s", {}, "sys", [])

    # First request logs the full initial delta…
    log.write_request(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        1, "m",
    )
    # …and the next request logs ONLY the one new message, not the whole list.
    log.write_request(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "yo"},
        ],
        2, "m",
    )

    lines = _read_log(tmp_path, "delta-test")
    assert [line["type"] for line in lines] == ["session", "request", "request"]
    assert lines[1]["delta"] == [{"role": "user", "content": "hi"}]
    assert lines[2]["delta"] == [{"role": "assistant", "content": "yo"}]
    # seq is strictly monotonic; the envelope is on every line.
    assert [line["seq"] for line in lines] == [0, 1, 2]
    assert all(line["session"] == "delta-test" for line in lines)
    assert all("ts" in line for line in lines)


def test_session_log_header_written_once(tmp_path):
    log = main.SessionLog("header-test", logs_dir=tmp_path)
    log.write_session("m", "http://x", "/s", {}, "sys", [])

    # A second SessionLog on the same file must not write the header again.
    again = main.SessionLog("header-test", logs_dir=tmp_path)
    again.write_session("m", "http://x", "/s", {}, "sys", [])

    lines = _read_log(tmp_path, "header-test")
    assert sum(1 for line in lines if line["type"] == "session") == 1


def test_session_log_resumes_without_re_logging_history(tmp_path):
    log = main.SessionLog("resume", logs_dir=tmp_path)
    log.write_session("m", "http://x", "/s", {}, "sys", [])
    log.write_request(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "a"}],
        1, "m",
    )
    log.write_response({"role": "assistant", "content": "b"}, 1, "m", 10, "stop", {})

    # Simulate the next turn in a fresh process: the browser replays [a, b]
    # plus a new message "c". Only "c" should be logged.
    log2 = main.SessionLog("resume", logs_dir=tmp_path)
    log2.write_request(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ],
        1, "m",
    )

    requests = [line for line in _read_log(tmp_path, "resume") if line["type"] == "request"]
    assert requests[-1]["delta"] == [{"role": "user", "content": "c"}]


def test_session_id_sanitizer():
    assert main.is_safe_session_id("abc-123-ABC")
    assert not main.is_safe_session_id("")
    assert not main.is_safe_session_id("../../etc/passwd")
    assert not main.is_safe_session_id("a b")


# --- prepare_session: rebuilding UI state from a log ------------------------

import pathlib as _pathlib

_REAL_LOG = _pathlib.Path(__file__).resolve().parent / "fixtures" / "371c7225-5c73-436a-81b8-70db500c92db.jsonl"


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _base_records(**over_env):
    """A minimal one-turn log: session header, one request, one response."""
    hdr = {"seq": 0, "ts": "2026-01-01T00:00:00+00:00", "session": "s1", "type": "session", "model": "m"}
    req = {"seq": 1, "ts": "2026-01-01T00:00:01+00:00", "session": "s1", "type": "request",
           "step": 1, "delta": [{"role": "user", "content": "hi"}], "total_messages": 1}
    res = {"seq": 2, "ts": "2026-01-01T00:00:02+00:00", "session": "s1", "type": "response",
           "step": 1, "message": {"role": "assistant", "content": "hello"}, "total_messages": 2}
    return [hdr, req, res]


def test_prepare_session_on_real_log():
    snaps = main.prepare_session(_REAL_LOG)
    assert len(snaps.turns) == 9
    assert snaps.warnings == []
    assert snaps.turns[0].user.startswith("Take a look at the jsonl file")
    first = snaps.turns[0]
    assert first.steps and first.steps[0].name == "bash"
    assert "command" in first.steps[0].args
    assert first.steps[0].result and "stdout" in first.steps[0].result
    # system message is excluded from the echoed history
    assert all(m.get("role") != "system" for m in snaps.messages)


def test_prepare_session_pairs_tool_calls_and_results(tmp_path):
    hdr = {"seq": 0, "type": "session", "session": "s1", "model": "m", "ts": "t0"}
    req1 = {"seq": 1, "type": "request", "step": 1, "total_messages": 1,
            "delta": [{"role": "user", "content": "go"}]}
    res1 = {"seq": 2, "type": "response", "step": 1, "total_messages": 2, "message": {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "bash", "arguments": json.dumps({"command": "ls"})}}]}}
    req2 = {"seq": 3, "type": "request", "step": 2, "total_messages": 3,
            "delta": [{"role": "tool", "tool_call_id": "c1", "name": "bash",
                       "content": json.dumps({"exit_code": 0, "stdout": "ok", "stderr": ""})}]}
    res2 = {"seq": 4, "type": "response", "step": 2, "total_messages": 4,
            "message": {"role": "assistant", "content": "done"}}
    path = _write_jsonl(tmp_path / "s1.jsonl", [hdr, req1, res1, req2, res2])
    snaps = main.prepare_session(path)
    turn = snaps.turns[0]
    assert turn.answer == "done"
    assert turn.steps[0].args == {"command": "ls"}
    assert turn.steps[0].result["stdout"] == "ok"


def test_prepare_session_multiple_tool_calls_one_message(tmp_path):
    recs = _base_records()
    recs[2]["message"] = {"role": "assistant", "content": "", "tool_calls": [
        {"id": "a", "function": {"name": "bash", "arguments": "{\"command\":\"1\"}"}},
        {"id": "b", "function": {"name": "bash", "arguments": "{\"command\":\"2\"}"}},
    ]}
    req = {"seq": 3, "type": "request", "step": 2, "total_messages": 3, "delta": [
        {"role": "tool", "tool_call_id": "a", "content": "{}"},
        {"role": "tool", "tool_call_id": "b", "content": "{}"}]}
    path = _write_jsonl(tmp_path / "s1.jsonl", recs + [req])
    turns = main.prepare_session(path).turns
    assert len(turns[0].steps) == 2


def test_prepare_session_incomplete_turn(tmp_path):
    # request with no response => turn has no answer => incomplete
    path = _write_jsonl(tmp_path / "s1.jsonl", _base_records()[:2])
    turns = main.prepare_session(path).turns
    assert turns[0].incomplete is True


def test_prepare_session_error_record_attached(tmp_path):
    recs = _base_records()[:2] + [
        {"seq": 2, "type": "error", "step": 1, "message": "boom"}]
    path = _write_jsonl(tmp_path / "s1.jsonl", recs)
    turns = main.prepare_session(path).turns
    assert turns[-1].error == "boom"
    assert not turns[-1].incomplete


def test_prepare_session_tolerates_bad_lines(tmp_path):
    recs = _base_records()
    path = tmp_path / "s1.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n{not json\n", encoding="utf-8")
    snaps = main.prepare_session(path)
    assert snaps.turns[0].answer == "hello"
    assert any("skipped" in w for w in snaps.warnings)


def test_prepare_session_header_only(tmp_path):
    path = _write_jsonl(tmp_path / "s1.jsonl", [{"seq": 0, "type": "session", "session": "s1"}])
    snaps = main.prepare_session(path)
    assert snaps.turns == [] and snaps.messages == []


def test_prepare_session_orphan_tool_result(tmp_path):
    recs = _base_records()
    recs.insert(2, {"seq": 99, "type": "request", "step": 9, "total_messages": 3,
                    "delta": [{"role": "tool", "tool_call_id": "zzz", "content": "{}"}]})
    path = _write_jsonl(tmp_path / "s1.jsonl", recs)
    snaps = main.prepare_session(path)
    assert any("orphan" in w for w in snaps.warnings)


def test_continuation_appends_without_re_logging(tmp_path):
    # After loading a session, continuing must append and continue seq.
    path = _write_jsonl(tmp_path / "s1.jsonl", _base_records())
    snaps = main.prepare_session(path)
    log = main.SessionLog("s1", logs_dir=tmp_path)
    log.write_request([{"role": "system", "content": "s"}] + snaps.messages
                      + [{"role": "user", "content": "next"}], 1, "m")
    lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    reqs = [l for l in lines if l["type"] == "request"]
    assert reqs[-1]["delta"] == [{"role": "user", "content": "next"}]  # only the new msg
    assert lines[-1]["seq"] == 2 + 1  # continued, not reset


# --- the two read-only endpoints -------------------------------------------

def test_list_sessions_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "LOGS_DIR", tmp_path)
    _write_jsonl(tmp_path / "aaaaa.jsonl", _base_records())
    _write_jsonl(tmp_path / "bbbbb.jsonl", _base_records())
    _write_jsonl(tmp_path / "empty.jsonl", [])  # should be hidden
    from fastapi.testclient import TestClient
    body = TestClient(main.app).get("/api/sessions").json()
    ids = [s["id"] for s in body["sessions"]]
    assert len(ids) == 2                 # the two non-empty files
    assert "empty" not in ids            # empty file hidden
    assert all(s["messages"] > 0 for s in body["sessions"])


def test_get_session_endpoint_404s(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "LOGS_DIR", tmp_path)
    _write_jsonl(tmp_path / "good.jsonl", _base_records())
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    assert c.get("/api/sessions/good").status_code == 200
    assert c.get("/api/sessions/nope").status_code == 404
    assert c.get("/api/sessions/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_prepare_session_repairs_unanswered_tool_call_at_tail(tmp_path):
    # A request was logged (write-ahead) but the model call died before the
    # assistant message and its tool results were appended. The replay must not
    # leave a dangling `tool_calls` message: the provider rejects that history.
    recs = _base_records()
    recs[2]["message"] = {"role": "assistant", "content": "about to run",
                          "tool_calls": [{"id": "a", "function": {"name": "bash",
                                          "arguments": "{\"command\":\"x\"}"}}]}
    path = _write_jsonl(tmp_path / "s1.jsonl", recs)  # no tool/tool message ever logged
    snaps = main.prepare_session(path)
    assert main._unanswered_tool_call_indexes(snaps.messages) == []
    last = snaps.messages[-1]
    assert "tool_calls" not in last and last["content"] == "about to run"
    assert snaps.turns[0].answer == "about to run"
    assert any("without tool results" in w for w in snaps.warnings)


def test_prepare_session_repairs_when_user_already_continued(tmp_path):
    # The user sent another message after the aborted turn; the assistant turn
    # becomes a native "continue" turn so the pending user message still answers.
    recs = _base_records()
    recs[2]["message"] = {"role": "assistant", "content": "",
                          "tool_calls": [{"id": "a", "function": {"name": "bash",
                                          "arguments": "{}"}}]}
    recs.append({"seq": 3, "type": "request", "step": 1, "total_messages": 3,
                 "delta": [{"role": "user", "content": "still there?"}]})
    path = _write_jsonl(tmp_path / "s1.jsonl", recs)
    snaps = main.prepare_session(path)
    msgs = snaps.messages
    assert main._unanswered_tool_call_indexes(msgs) == []
    assert msgs[-2]["role"] == "assistant" and msgs[-2]["content"].strip()
    assert msgs[-1] == {"role": "user", "content": "still there?"}


def test_prepare_session_null_content_becomes_string(tmp_path):
    recs = _base_records()
    recs[2]["message"] = {"role": "assistant", "content": None,
                          "tool_calls": [{"id": "a", "function": {"name": "bash",
                                          "arguments": "{}"}}]}
    recs.append({"seq": 3, "type": "request", "step": 2, "total_messages": 3,
                 "delta": [{"role": "tool", "tool_call_id": "a", "content": "{}"}]})
    path = _write_jsonl(tmp_path / "s1.jsonl", recs)
    msgs = main.prepare_session(path).messages
    assert all(isinstance(m.get("content"), str) for m in msgs)


def test_session_log_self_heals_cursor_after_lost_turn(tmp_path):
    # write_response bumped the cursor, but the turn died before the tool
    # messages were logged. A later request must still log its new user message
    # instead of silently skipping it (which is what broke 098ca653).
    log = main.SessionLog("s1", logs_dir=tmp_path)
    log.write_request([{"role": "system", "content": "s"},
                       {"role": "user", "content": "1"}], 1, "m")
    log.write_response({"role": "assistant", "content": "x",
                        "tool_calls": [{"id": "a"}]}, 1, "m", 0, "tool_calls", None)
    # Cursor says 2 messages logged; the file really has 1 (assistant only).
    log2 = main.SessionLog("s1", logs_dir=tmp_path)
    log2.write_request([{"role": "system", "content": "s"},
                        {"role": "user", "content": "1"},
                        {"role": "assistant", "content": "x"},
                        {"role": "user", "content": "2"}], 1, "m")
    reqs = [json.loads(l) for l in tmp_path.joinpath("s1.jsonl").read_text().splitlines()
            if l.strip()]
    reqs = [r for r in reqs if r.get("type") == "request"]
    assert reqs[-1]["delta"] == [{"role": "user", "content": "2"}]


# --- session ordering -------------------------------------------------------
# Ordering happens on datetimes, on the server. These pin the two things a
# string sort got wrong: differing UTC offsets, and sessions with no records.

def _write_log(tmp_path, name, stamps):
    """One session header + one response per stamp (all in file/seq order)."""
    recs = [{"seq": 0, "type": "session", "session": name, "ts": stamps[0] if stamps else None}]
    for i, ts in enumerate(stamps[1:], start=1):
        recs.append({"seq": i, "type": "response", "step": i, "total_messages": i,
                     "ts": ts, "message": {"role": "assistant", "content": "ok"}})
    return _write_jsonl(tmp_path / f"{name}.jsonl", recs)


def test_parse_ts_is_timezone_aware_utc():
    # Same instant, written two ways: equal datetimes, unequal strings.
    a = main._parse_ts("2026-11-02T15:06:36+00:00")
    b = main._parse_ts("2026-11-02T16:06:36+01:00")
    assert a == b
    assert a.tzinfo is not None and a.utcoffset().total_seconds() == 0
    # A missing offset is treated as UTC rather than failing.
    assert main._parse_ts("2026-11-02T15:06:36").tzinfo is not None
    assert main._parse_ts("not a date") is None
    assert main._parse_ts(None) is None


def test_list_sessions_sorts_on_datetime_not_string(tmp_path, monkeypatch):
    # "16:06+01:00" is 15:06 UTC: *earlier* than "15:30+00:00", though it sorts
    # after it as a plain string.
    _write_log(tmp_path, "later", ["2026-11-02T15:30:00+00:00", "2026-11-02T15:30:00+00:00"])
    _write_log(tmp_path, "earlier", ["2026-11-02T16:06:00+01:00", "2026-11-02T16:06:00+01:00"])
    monkeypatch.setattr(main, "LOGS_DIR", tmp_path)
    body = asyncio.run(main.list_sessions())
    assert [s["id"] for s in body["sessions"]] == ["later", "earlier"]


def test_list_sessions_newest_first_uses_latest_record(tmp_path, monkeypatch):
    _write_log(tmp_path, "old", ["2026-01-01T00:00:00+00:00", "2026-01-01T00:00:01+00:00"])
    _write_log(tmp_path, "new", ["2026-01-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00"])
    monkeypatch.setattr(main, "LOGS_DIR", tmp_path)
    body = asyncio.run(main.list_sessions())
    assert [s["id"] for s in body["sessions"]] == ["new", "old"]


def test_list_sessions_header_only_falls_back_to_mtime(tmp_path, monkeypatch):
    # No dated record: fall back to the file's real mtime, not the epoch.
    path = _write_log(tmp_path, "bare", [])
    monkeypatch.setattr(main, "LOGS_DIR", tmp_path)
    meta = asyncio.run(main.list_sessions())["sessions"][0]
    assert meta["id"] == "bare"
    assert meta["updated"] == main.datetime.fromtimestamp(
        path.stat().st_mtime, tz=main.timezone.utc)


def test_session_meta_has_no_string_sorted_fields(tmp_path):
    path = _write_log(tmp_path, "s1", ["2026-01-01T00:00:00+00:00"])
    meta = main._session_meta(path)
    assert "modified_at" not in meta          # ambiguous, dropped
    assert isinstance(meta["updated"], main.datetime)
    assert isinstance(meta["created"], main.datetime)
