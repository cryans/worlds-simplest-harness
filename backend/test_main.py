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
