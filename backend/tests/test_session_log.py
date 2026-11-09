"""SessionLog: append-only WAL, header-once, resume, cursor self-heal."""

import json

from wsh.config import SAMPLE_PROJECT
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


def test_tool_messages_after_last_response_are_not_re_emitted(tmp_path):
    """A resumed request must not re-emit messages already in the file.

    Regression for the broken driver session: after a tool round-trip is fully
    recorded (request + response + following request carrying the ``tool``
    result), the ``_resume`` cursor must count the messages *actually recorded*
    (request deltas + one per response) rather than the stored
    ``total_messages`` field. That field drifts after an aborted turn — a
    ``response`` records its count before the loop appends the following
    ``tool`` results — so trusting it makes the next ``write_request`` re-emit
    already-known ``tool``/``assistant`` messages as new deltas, corrupting the
    wire history into a ``tool``-before-``tool_calls`` 400 error.
    """
    log = SessionLog("tool-tail", logs_dir=tmp_path)
    log.write_session("m", "http://x", "/s", {}, "sys", [])
    # A full tool round-trip, all recorded:
    #   user -> assistant(tool_calls) -> tool result -> assistant(stop)
    convo = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "a"},
    ]
    log.write_request(convo, 1, "m")

    convo.append({"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]})
    log.write_response(convo[-1], 1, "m", 10, "tool_calls", {})

    convo.append({"role": "tool", "tool_call_id": "t1", "content": "out"})
    log.write_request(convo, 2, "m")

    convo.append({"role": "assistant", "content": "done"})
    log.write_response(convo[-1], 2, "m", 10, "stop", {})

    # Resume on a later turn: the browser echoes the full history + a new user
    # message. None of the already-recorded messages may be re-emitted.
    resumed = SessionLog("tool-tail", logs_dir=tmp_path)
    full = convo + [{"role": "user", "content": "b"}]
    resumed.write_request(full, 3, "m")

    reqs = [r for r in _read_log(tmp_path, "tool-tail") if r.get("type") == "request"]
    assert reqs[-1]["delta"] == [{"role": "user", "content": "b"}], reqs[-1]["delta"]


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


def test_session_log_resumes_sandbox_from_header(tmp_path):
    log = SessionLog("s", logs_dir=tmp_path)
    log.write_session("m", "http://x", str(tmp_path / "smoke"), {}, "sys", [])

    resumed = SessionLog("s", logs_dir=tmp_path)
    assert resumed.sandbox == tmp_path / "smoke"


def test_session_log_default_sandbox(tmp_path):
    log = SessionLog("s", logs_dir=tmp_path)
    assert log.sandbox == SAMPLE_PROJECT


def test_session_log_resumes_latest_sandbox_override(tmp_path):
    log = SessionLog("s", logs_dir=tmp_path)
    log.write_session("m", "http://x", str(tmp_path / "smoke"), {}, "sys", [])
    log.write_sandbox(tmp_path / "normal")

    resumed = SessionLog("s", logs_dir=tmp_path)
    assert resumed.sandbox == tmp_path / "normal"


def test_session_log_default_mode(tmp_path):
    log = SessionLog("s", logs_dir=tmp_path)
    assert log.mode == "normal"


def test_session_log_resumes_mode_from_header(tmp_path):
    log = SessionLog("s", logs_dir=tmp_path, mode="smoke")
    log.write_session("m", "http://x", str(tmp_path / "smoke"), {}, "sys", [], mode="smoke")

    resumed = SessionLog("s", logs_dir=tmp_path)
    assert resumed.mode == "smoke"


def test_session_log_resumes_latest_mode_override(tmp_path):
    log = SessionLog("s", logs_dir=tmp_path, mode="smoke")
    log.write_session("m", "http://x", str(tmp_path / "smoke"), {}, "sys", [], mode="smoke")
    log.write_mode("normal")

    resumed = SessionLog("s", logs_dir=tmp_path)
    assert resumed.mode == "normal"
