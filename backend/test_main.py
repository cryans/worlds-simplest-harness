"""Tests for the @tool decorator, registry, and the pieces it wires together.

Run from backend/ with:
    .venv/bin/python -m pytest -q
"""

import asyncio

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
