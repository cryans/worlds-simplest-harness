---
title: "plans/feature-event-loop-cleanup-design.md"
branch: "feature/event-loop-cleanup"
feature: "event-loop-cleanup"
status: "in-progress"
references:
  - "plans/next-steps.md"
  - "plans/feature-event-loop-cleanup-requirements.md"
---

# Feature: Event Loop Cleanup & Typed SSE Contract — Design

## 1. Context & Structural Intent

The event loop is the north star: ask → tool-call → result → answer, streamed over
SSE, logged write-ahead, replayable. The goal is to make the loop *produce* the
contract rather than emit a hand-encoded shadow of it.

Today one shape is written twice:

- **In code** — `agent_loop` yields `sse("answer", {...})` strings, with `sse()`
  doing framing *and* injecting `"type"` into the payload.
- **In a schema** — `models.SseEvent` is the same union, reflected into OpenAPI by
  `app.custom_openapi`, but never produced by the loop.

This design collapses the two: the loop yields `SseEvent` models, and `sse(model)`
is the single encoder.

---

## 2. Sequence Lifecycle

The loop is one outer iteration (ask → branch → repeat) around an inner tool-call
loop. The diagram makes that nesting explicit with a label on the outer `loop` and a
dedicated swimlane for the tool-call loop (`⟳ tool-call loop`), whose own nested
`loop each tool call` routes each dispatch → execute → result cycle through it.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Agent as agent_loop
    participant Convo as Message Stack
    participant LLM as Model API
    participant ToolLoop as ⟳ tool-call loop
    participant System as Tool Runner
    participant SSE as SSE Stream

    User->>Agent: Submit Prompt
    Agent->>SSE: yield SessionEvent (session)

    Note over Agent,LLM: ─── OUTER LOOP: Step 1..MAX_STEPS ───

    loop each step
        Agent->>Convo: Read message stack
        Agent->>SSE: yield StatusEvent (status)
        Agent->>LLM: Call model(messages)
        LLM-->>Agent: Return response (prose or tool_calls)

        alt Tool Calls Requested
            Agent->>Convo: Append assistant tool-call message
            Agent->>SSE: yield ToolCallEvent (tool_call)

            loop each tool call
                Agent->>ToolLoop: dispatch tool
                ToolLoop->>System: Execute tool(s)
                System-->>ToolLoop: Tool results
                ToolLoop-->>Agent: result
            end

            Agent->>SSE: yield ToolResultEvent (tool_result)
            Agent->>Convo: Append tool results to stack

        else No Tool Calls → Final Answer
            Agent->>Convo: Append assistant prose message
            Agent->>SSE: yield AnswerEvent (answer)
            Agent-->>User: Stream complete (Turn Settled)

        else Error / Max Steps
            Agent->>SSE: yield ErrorEvent (error)
            Agent-->>User: Stream complete (Turn Errored)
        end

        Note over Agent,LLM: ⤴ back to "Call model(messages)" after tool results
    end
```

### A single `Note over` is the boundary

The one piece this diagram can't draw as a literal back-arrow is the loop-back from
`tool_results` to the *next* `Call model`. Mermaid sequence diagrams have no goto;
the idiomatic way to convey it is exactly what the diagram does:

- the **outer `loop`** owns the outer repeat (you always come back to the top),
- the **`⟳ tool-call loop` swimlane** owns the inner repeat (one dispatch/execute/
  result cycle per tool, via its nested `loop each tool call`), and
- the trailing **`Note over Agent,LLM: ⤴ back to "Call model(messages)"`** names the
  return path after a batch of tool results.

No dedicated event carries this transition — it is the loop's implicit "next
iteration of the `for step` body".
