"""The ``bash`` tool: run a command inside sample-project/."""

import asyncio

from wsh.config import BASH_TIMEOUT, SAMPLE_PROJECT
from wsh.tools.registry import tool


async def run_bash(command: str) -> dict:
    """Run a shell command inside sample-project/ and capture its output."""
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=SAMPLE_PROJECT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=BASH_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {"exit_code": None, "stdout": "", "stderr": f"(timed out after {BASH_TIMEOUT}s)"}

    return {
        "exit_code": proc.returncode,
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
    }


@tool
async def bash(command: str) -> dict:
    """Run a bash command inside the project folder. Use it to read, write, and run files there."""
    return await run_bash(command)
