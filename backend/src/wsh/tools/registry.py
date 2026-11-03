"""Tool registry: the ``@tool`` decorator, the model-facing schema list, and dispatch."""

import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

from pydantic import create_model

# What we send to the model: one entry per registered tool.
TOOLS: list[dict] = []

# Name -> the actual function, so the agent loop can call the right one.
TOOL_REGISTRY: dict[str, Callable] = {}


def tool(func: Callable) -> Callable:
    """Register a function as a callable tool.

    Reads the function's name, docstring, and type hints to generate the
    OpenAI "tool calling" schema automatically — the same shape that used to
    be written by hand.
    """
    name = func.__name__
    description = (func.__doc__ or "").strip()

    # Resolve type hints, dropping the return annotation (not a parameter).
    hints = get_type_hints(func)
    hints.pop("return", None)

    # Build a pydantic model from the parameters; it generates the JSON Schema.
    fields: dict[str, Any] = {}
    for param_name, param in inspect.signature(func).parameters.items():
        field_type = hints.get(param_name, Any)
        if param.default is inspect.Parameter.empty:
            fields[param_name] = (field_type, ...)            # required
        else:
            fields[param_name] = (field_type, param.default)  # optional

    parameters = create_model(name, **fields).model_json_schema()

    # The same information feeds two consumers:
    TOOL_REGISTRY[name] = func  # the agent loop calls it by name
    TOOLS.append(                # the model reads its schema
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
    )
    return func


async def call_tool(func: Callable, args: dict):
    """Call a registered tool with parsed args, awaiting if it's a coroutine."""
    result = func(**args)
    if inspect.iscoroutine(result):
        result = await result
    return result
