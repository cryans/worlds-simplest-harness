"""Tool registry, call_tool, and the bash tool."""

import asyncio

import wsh.tools.bash
from wsh.config import SAMPLE_PROJECT, reset_current_sandbox, set_current_sandbox
from wsh.tools import TOOLS, TOOL_REGISTRY, call_tool, run_bash, tool


def test_registry_has_bash_with_generated_schema():
    assert "bash" in TOOL_REGISTRY
    entry = next(t for t in TOOLS if t["function"]["name"] == "bash")
    fn = entry["function"]
    params = fn["parameters"]

    assert entry["type"] == "function"
    assert fn["name"] == "bash"
    assert "Run a bash command" in fn["description"]

    assert params["type"] == "object"
    assert params["properties"]["command"]["type"] == "string"
    assert params["required"] == ["command"]


def test_decorator_registers_custom_tool():
    @tool
    async def add(a: int, b: int = 0) -> int:
        """Add two numbers."""
        return a + b

    try:
        assert TOOL_REGISTRY["add"] is add

        entry = next(t for t in TOOLS if t["function"]["name"] == "add")
        params = entry["function"]["parameters"]

        assert entry["function"]["description"] == "Add two numbers."
        assert params["properties"]["a"]["type"] == "integer"
        assert params["properties"]["b"]["type"] == "integer"
        assert params["required"] == ["a"]  # b has a default
    finally:
        TOOL_REGISTRY.pop("add", None)
        TOOLS[:] = [t for t in TOOLS if t["function"]["name"] != "add"]


def test_call_tool_sync_and_async():
    def double(x: int) -> int:
        return x * 2

    async def triple(x: int) -> int:
        return x * 3

    assert asyncio.run(call_tool(double, {"x": 21})) == 42
    assert asyncio.run(call_tool(triple, {"x": 14})) == 42


def test_run_bash_cwd_and_stdout(tmp_path, monkeypatch):
    monkeypatch.setattr(wsh.tools.bash, "get_current_sandbox", lambda: tmp_path)
    result = asyncio.run(run_bash("pwd && echo hello"))

    assert result["exit_code"] == 0
    assert str(tmp_path) in result["stdout"]
    assert result["stdout"].strip().splitlines()[-1] == "hello"


def test_run_bash_reports_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(wsh.tools.bash, "get_current_sandbox", lambda: tmp_path)
    result = asyncio.run(run_bash("exit 3"))
    assert result["exit_code"] == 3


def test_run_bash_times_out(tmp_path, monkeypatch):
    monkeypatch.setattr(wsh.tools.bash, "BASH_TIMEOUT", 1)
    monkeypatch.setattr(wsh.tools.bash, "get_current_sandbox", lambda: tmp_path)
    result = asyncio.run(run_bash("sleep 3"))

    assert result["exit_code"] is None
    assert "timed out" in result["stderr"]


def test_run_bash_uses_current_sandbox(tmp_path):
    async def scenario():
        token = set_current_sandbox(tmp_path)
        try:
            return await run_bash("pwd")
        finally:
            reset_current_sandbox(token)

    result = asyncio.run(scenario())
    assert result["exit_code"] == 0
    assert str(tmp_path) in result["stdout"]
