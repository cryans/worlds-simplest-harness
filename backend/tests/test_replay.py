"""prepare_session: rebuild UI state, tolerating and repairing malformed logs."""

import json
import pathlib

from wsh.session import _unanswered_tool_call_indexes, prepare_session

_REAL_LOG = (
    pathlib.Path(__file__).resolve().parent
    / "fixtures"
    / "371c7225-5c73-436a-81b8-70db500c92db.jsonl"
)


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


def test_prepare_session_on_real_log():
    snaps = prepare_session(_REAL_LOG)
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
    snaps = prepare_session(path)
    turn = snaps.turns[0]
    assert turn.answer == "done"
    assert turn.steps[0].args == {"command": "ls"}
    assert turn.steps[0].result["stdout"] == "ok"


def test_prepare_session_incomplete_turn(tmp_path):
    # request with no response => turn has no answer => incomplete
    path = _write_jsonl(tmp_path / "s1.jsonl", _base_records()[:2])
    turns = prepare_session(path).turns
    assert turns[0].incomplete is True


def test_prepare_session_error_record_attached(tmp_path):
    recs = _base_records()[:2] + [
        {"seq": 2, "type": "error", "step": 1, "message": "boom"}]
    path = _write_jsonl(tmp_path / "s1.jsonl", recs)
    turns = prepare_session(path).turns
    assert turns[-1].error == "boom"
    assert not turns[-1].incomplete


def test_prepare_session_tolerates_bad_lines(tmp_path):
    recs = _base_records()
    path = tmp_path / "s1.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n{not json\n", encoding="utf-8")
    snaps = prepare_session(path)
    assert snaps.turns[0].answer == "hello"
    assert any("skipped" in w for w in snaps.warnings)


def test_prepare_session_orphan_tool_result(tmp_path):
    recs = _base_records()
    recs.insert(2, {"seq": 99, "type": "request", "step": 9, "total_messages": 3,
                    "delta": [{"role": "tool", "tool_call_id": "zzz", "content": "{}"}]})
    path = _write_jsonl(tmp_path / "s1.jsonl", recs)
    snaps = prepare_session(path)
    assert any("orphan" in w for w in snaps.warnings)


def test_prepare_session_repairs_unanswered_tool_call_at_tail(tmp_path):
    recs = _base_records()
    recs[2]["message"] = {"role": "assistant", "content": "about to run",
                          "tool_calls": [{"id": "a", "function": {"name": "bash",
                                          "arguments": "{\"command\":\"x\"}"}}]}
    path = _write_jsonl(tmp_path / "s1.jsonl", recs)
    snaps = prepare_session(path)
    assert _unanswered_tool_call_indexes(snaps.messages) == []
    last = snaps.messages[-1]
    assert "tool_calls" not in last and last["content"] == "about to run"
    assert snaps.turns[0].answer == "about to run"
    assert any("without tool results" in w for w in snaps.warnings)


def test_prepare_session_repairs_when_user_already_continued(tmp_path):
    recs = _base_records()
    recs[2]["message"] = {"role": "assistant", "content": "",
                          "tool_calls": [{"id": "a", "function": {"name": "bash",
                                          "arguments": "{}"}}]}
    recs.append({"seq": 3, "type": "request", "step": 1, "total_messages": 3,
                 "delta": [{"role": "user", "content": "still there?"}]})
    path = _write_jsonl(tmp_path / "s1.jsonl", recs)
    snaps = prepare_session(path)
    msgs = snaps.messages
    assert _unanswered_tool_call_indexes(msgs) == []
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
    msgs = prepare_session(path).messages
    assert all(isinstance(m.get("content"), str) for m in msgs)
