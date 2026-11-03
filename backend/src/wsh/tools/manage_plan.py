"""The ``manage_plan`` tool: read/write a markdown plan or todo file."""

import os

from wsh.tools.registry import tool


@tool
def manage_plan(filename: str, content: str, mode: str = "write") -> str:
    """
    Manage an agent plan or todo list as a plain markdown file.

    Args:
        filename: Path to the markdown file (e.g., 'plan.md' or 'todo.md').
        content: The markdown content or task updates to write/append.
        mode: Operation mode - 'write' (overwrite/create), 'append' (add to end), or 'read'.

    Returns:
        Status message or current content of the file.
    """
    try:
        # Ensure we stay safe in the current workspace directory
        filepath = os.path.normpath(filename)

        if mode == "read":
            if not os.path.exists(filepath):
                return f"Plan file '{filename}' does not exist yet."
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()

        elif mode == "append":
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(f"\n{content}")
            return f"Successfully appended update to '{filename}'."

        elif mode == "write":
            # Ensure target parent directories exist
            os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully saved plan to '{filename}'."

        else:
            return f"Error: Invalid mode '{mode}'. Choose 'write', 'append', or 'read'."

    except Exception as e:
        return f"Failed to perform '{mode}' operation on '{filename}': {str(e)}"
