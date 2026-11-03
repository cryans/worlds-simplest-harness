"""Tool registry and the built-in tools (``bash``, ``manage_plan``)."""

from wsh.tools.registry import TOOL_REGISTRY, TOOLS, call_tool, tool
from wsh.tools.bash import run_bash  # noqa: F401  (also registers the `bash` tool)

import wsh.tools.manage_plan  # noqa: F401  (registers the `manage_plan` tool)

__all__ = ["tool", "TOOLS", "TOOL_REGISTRY", "call_tool", "run_bash"]
