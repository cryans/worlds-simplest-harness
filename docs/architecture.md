# Architecture

## The pieces

```
browser ──► React/Vite (frontend) ──► FastAPI (backend) ──► DeepSeek API
                                          │
                                          └── bash tool ──► sample-project/
```

Everything funnels through **one endpoint**: `POST /api/chat`.

## The agent loop

This is the single idea that makes it a *harness*. In `backend/src/wsh/agent/loop.py`,
`agent_loop()` repeats:

1. **Ask the model** — send the conversation plus the list of tools (`TOOLS`).
2. **No tool call?** The model answered in words → stream the answer and stop.
3. **Tool call?** Look the tool's name up in `TOOL_REGISTRY`, run it, capture
   its output, feed that output back to the model, and go back to step 1.

Each step is capped by `MAX_STEPS` so a confused model can't loop forever.

## Streaming events

The backend streams Server-Sent Events (SSE) to the browser so you can watch
the loop happen. Event types:

| Event | Payload | Meaning |
| --- | --- | --- |
| `status` | `{text}` | The loop is asking the model |
| `tool_call` | `{name, args}` | The model asked to run a tool |
| `tool_result` | `{name, result}` | That tool's output (stdout/stderr/exit code) |
| `answer` | `{content, messages}` | The final text, plus the new full history |
| `error` | `{message}` | Something went wrong |

## Stateless by design

The backend holds no session. The browser sends the full message history every
turn, and the final `answer` event returns the updated history (including any
`tool` messages), which the browser echoes back next turn.
