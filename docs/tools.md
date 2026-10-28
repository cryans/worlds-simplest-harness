# Tools

The harness has **one tool**: `bash`. Instead of hand-writing the OpenAI schema
for it, we describe it as a normal Python function and let the `@tool`
decorator generate the schema.

## The `@tool` decorator

```python
@tool
async def bash(command: str) -> dict:
    """Run a bash command inside the project folder. Use it to read, write, and run files there."""
    return await run_bash(command)
```

The decorator reads three things from the function and builds the model-facing
schema from them:

| From the function | Becomes |
| --- | --- |
| `func.__name__` | the tool's `name` (`"bash"`) |
| the docstring | the tool's `description` |
| the type hints (`command: str`) | the `parameters` JSON Schema |

It uses pydantic (`create_model` + `model_json_schema()`) to turn the type
hints into JSON Schema, so a parameter with no default is `required`, and a
parameter with a default is optional.

## Two consumers of the same information

Registering a tool updates two module-level structures:

- **`TOOLS`** — a `list[dict]` sent to the model so it knows what tools exist.
- **`TOOL_REGISTRY`** — a `dict` mapping tool name → function, used by the
  agent loop to actually run the tool.

```python
TOOL_REGISTRY[name] = func   # the agent loop calls it by name
TOOLS.append({...})          # the model reads its schema
```

## Adding a second tool

Add a function, decorate it, done:

```python
@tool
async def read_file(path: str) -> dict:
    """Read a file inside the project folder and return its contents."""
    return {"content": (SAMPLE_PROJECT / path).read_text()}
```

It's immediately available to the model — no schema to write by hand. Two
things to keep in mind:

1. **`call_tool` handles both sync and async.** It awaits the result only if it
   is a coroutine, so `def` tools work too.
2. **Update `SYSTEM_PROMPT`.** It currently tells the model there is "ONE tool:
   `bash`" — add a line for any new tool.

## How tools are called

In `agent_loop()`, each `tool_calls` entry is dispatched through the registry:

```python
func = TOOL_REGISTRY.get(name)   # None -> "unknown tool" error
args = json.loads(fn.get("arguments") or "{}")
result = await call_tool(func, args)
```

The result is serialized into a `tool` message and fed back to the model.
