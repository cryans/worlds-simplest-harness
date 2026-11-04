"""SessionLog: append-only WAL, header-once, resume, cursor self-heal."""

import json

from wsh.session import SessionLog


def _read_log(tmp_path, session_id):
    return [
        json.loads(line)
        for line in (tmp_path / f"{session_id}.jsonl").read_text().splitlines()
        if line.strip()
    ]


def test_session_log_writes_deltas_not_cumulative_history(tmp_path):
    log = SessionLog("delta-test", logs_dir=tmp_path)
    log.write_session("m", "http://x", "/s", {}, "sys", [])

    log.write_request(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        1, "m",
    )
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
    assert [line["seq"] for line in lines] == [0, 1, 2]
    assert all(line["session"] == "delta-test" for line in lines)
    assert all("ts" in line for line in lines)


def test_session_log_header_written_once(tmp_path):
    log = SessionLog("header-test", logs_dir=tmp_path)
    log.write_session("m", "http://x", "/s", {}, "sys", [])

    again = SessionLog("header-test", logs_dir=tmp_path)
    again.write_session("m", "http://x", "/s", {}, "sys", [])

    lines = _read_log(tmp_path, "header-test")
    assert sum(1 for line in lines if line["type"] == "session") == 1


def test_session_log_resumes_without_re_logging_history(tmp_path):
    log = SessionLog("resume", logs_dir=tmp_path)
    log.write_session("m", "http://x", "/s", {}, "sys", [])
    log.write_request(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "a"}],
        1, "m",
    )
    log.write_response({"role": "assistant", "content": "b"}, 1, "m", 10, "stop", {})

    log2 = SessionLog("resume", logs_dir=tmp_path)
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


def test_session_log_self_heals_cursor_after_lost_turn(tmp_path):
    log = SessionLog("s1", logs_dir=tmp_path)
    log.write_request([{"role": "system", "content": "s"},
                       {"role": "user", "content": "1"}], 1, "m")
    log.write_response({"role": "assistant", "content": "x",
                        "tool_calls": [{"id": "a"}]}, 1, "m", 0, "tool_calls", None)

    # Cursor says 2 messages logged; the file really has 1 (assistant only).
    log2 = SessionLog("s1", logs_dir=tmp_path)
    log2.write_request([{"role": "system", "content": "s"},
                        {"role": "user", "content": "1"},
                        {"role": "assistant", "content": "x"},
                        {"role": "user", "content": "2"}], 1, "m")

    reqs = [json.loads(l) for l in tmp_path.joinpath("s1.jsonl").read_text().splitlines()
            if l.strip()]
    reqs = [r for r in reqs if r.get("type") == "request"]
    assert reqs[-1]["delta"] == [{"role": "user", "content": "2"}]


def test_next_step_resumes_across_reopen(tmp_path):
    log = SessionLog("steps", logs_dir=tmp_path)
    log.write_session("m", "http://x", "/s", {}, "sys", [])
    log.write_request([{"role": "system", "content": "sys"},
                       {"role": "user", "content": "hi"}], 1, "m")
    log.write_request([{"role": "system", "content": "sys"},
                       {"role": "user", "content": "hi"},
                       {"role": "assistant", "content": "yo"}], 2, "m")

    # max(step) was 2, so a fresh SessionLog resumes at 3 — no per-turn reset.
    assert SessionLog("steps", logs_dir=tmp_path).next_step() == 3
