---
schema: "feature-load-jsonl-UI-Mockup"
branch: "feature/load-jsonl"
references: []
---

# Load chat sessions from JSONL logs — UI mockup

```
┌─────────────────────────────┬──────────────────────────────────────┐
│ World's Simplest Harness     │                                      │
├─────────────────────────────┼──────────────────────────────────────┤
│  [ + New chat ]              │  ┌─ user ────────────────────────┐   │
│                              │  │ Take a look at the jsonl file… │   │
│  2026-11-02 14:01:21  371c7  │  └───────────────────────────────┘   │
│  ▸2026-10-28 17:46:55  0fbd4 │  ┌─ tool call: bash ─────────────┐   │
│  2026-10-28 17:40:06  0d641  │  │ $ ls -la; find . -name *.jsonl │   │
│  2026-10-28 17:36:26  2ad4d  │  │ total 56 …                     │   │
│  2026-10-28 17:26:15  a237e  │  └───────────────────────────────┘   │
│  …                           │  ┌─ assistant ───────────────────┐   │
│                              │  │ The log has 39 lines across …  │   │
│                              │  └───────────────────────────────┘   │
│                              │                                      │
├─────────────────────────────┴──────────────────────────────────────┤
│  [ Ask the harness to do something…                 ]  [ Send ]     │
└─────────────────────────────────────────────────────────────────────┘
```

- Left: session list, timestamp-then-id, newest first, selected item highlighted (`▸`). Disabled while busy.
- Right: the same `<TurnView>` used live (user / tool-call / assistant boxes).
- Bottom: the existing input footer. "New chat" clears the transcript and `?session=`.
