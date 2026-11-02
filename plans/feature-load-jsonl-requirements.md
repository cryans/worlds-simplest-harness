---
schema: "feature-load-jsonl-requirements"
branch: "feature/load-jsonl"
references:
  - doc: "feature-load-jsonl-design.md"
---

# Load chat sessions from JSONL logs — requirements

## Goal
After a restart the UI loses the conversation even though the chat is on disk. Let a user browse the
available session logs and open one, rendering its transcript in the main window — **chat state only**,
no mutation replay (no bash, no model call).

## Requirements
- **Sidebar** lists available `logs/*.jsonl` sessions.
- **Each item:** local `yyyy-mm-dd hh-mm-ss` timestamp **first**, then the **first 5 chars** of the
  session id. No tooltips. Timestamp = last-modified (more useful than the id).
- **Order:** most recent first, oldest last.
- **Selecting** a session renders its transcript in the main "chat" window (same look as a live session).
- **Continuing:** sending a message after opening a session appends to that same log file.
- **"New chat"** button to start a fresh conversation.
- Show incomplete/failed turns rather than hiding them. Hide empty session files from the list.
- Deep-link selection via `?session=<id>` so a reload re-opens it.

## Out of scope
Replaying tool runs / restoring `sample-project/` files; auth/multi-user; delete/rename; editing or
branching history.
