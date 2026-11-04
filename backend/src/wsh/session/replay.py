"""Read a session log back into UI state. Read-only; never calls the model."""

import json
from pathlib import Path
from typing import Any

from wsh.models import SessionPayload


def read_records(path: Path) -> tuple[list[dict], int]:
    """Read a JSONL file into ``(records, skipped)``.

    Records are returned in file order (which is ``seq`` order). Blank lines and
    lines that aren't valid JSON (e.g. a torn trailing write after a crash) are
    skipped and counted, never raised.
    """
    records: list[dict] = []
    skipped = 0
    if not path.exists():
        return records, skipped
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(rec, dict):
            records.append(rec)
        else:
            skipped += 1
    return records, skipped


def _parse_json_arg(value: Any, default: Any) -> Any:
    """Tool args/results are JSON strings in the log; decode defensively."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _unanswered_tool_call_indexes(messages: list[dict]) -> list[int]:
    """Indexes of assistant messages whose ``tool_calls`` lack replies.

    A message is dangling when any of its ``tool_call_id``s has no ``tool``
    message in the run of messages immediately following it (the OpenAI wire
    format requires the replies to be adjacent, in any order).
    """
    dangling: list[int] = []
    for i, msg in enumerate(messages):
        ids = {tc.get("id") for tc in (msg.get("tool_calls") or []) if isinstance(tc, dict)}
        ids.discard(None)
        if msg.get("role") != "assistant" or not ids:
            continue
        answered: set = set()
        for nxt in messages[i + 1 :]:
            if nxt.get("role") != "tool":
                break
            answered.add(nxt.get("tool_call_id"))
            if ids <= answered:
                break
        if not ids <= answered:
            dangling.append(i)
    return dangling


def prepare_session(path: Path) -> SessionPayload:
    """Rebuild UI-only state from a session log. Read-only; never calls the model.

    Concatenates every ``request.delta`` and ``response.message`` in order to
    rebuild the OpenAI-format message list (system message excluded), then groups
    it into ``turns`` shaped like the frontend's ``Turn``:

        {user, steps: [{name, args, result}], answer, error?, incomplete?}

    Tolerates malformed input: bad lines are skipped (and warned about), unknown
    roles are ignored, and orphan tool results are dropped from rendering.
    """
    records, skipped = read_records(path)
    warnings: list[str] = []
    if skipped:
        warnings.append(f"skipped {skipped} unreadable line(s)")

    header: dict = {}
    messages: list[dict] = []
    errors_by_turn: dict[int, str] = {}
    turn_index = -1

    for rec in records:
        rtype = rec.get("type")
        if rtype == "session":
            header = rec
        elif rtype == "request":
            delta = rec.get("delta") or []
            if isinstance(delta, list):
                for m in delta:
                    if not isinstance(m, dict):
                        continue
                    if m.get("role") == "user":
                        turn_index += 1
                    messages.append(m)
        elif rtype == "response":
            msg = rec.get("message")
            if isinstance(msg, dict):
                messages.append(msg)
        elif rtype == "error":
            errors_by_turn[turn_index] = rec.get("message", "error")

    # Logs written before null-coercion existed can carry `content: null` on an
    # assistant tool-call turn; the OpenAI wire format wants a string there.
    for msg in messages:
        if msg.get("content") is None:
            msg["content"] = ""

    # A request is logged write-ahead, *before* the model call. If that call
    # failed (or the turn is still running), the last assistant message asks for
    # tools whose results were never logged. Such a conversation is invalid for
    # the model: every `tool_calls` id must have a matching `tool` message. Two
    # cases, both repaired by dropping the outgoing assistant's tool_calls:
    #   * the request is the final message  -> prose + finish_reason=stop
    #   * later messages exist (the user already sent a new turn) -> native
    #     "continue" assistant turn, so the pending user message still answers it
    dangling = _unanswered_tool_call_indexes(messages)
    if dangling:
        warnings.append(
            f"{len(dangling)} assistant request(s) without tool results; dropped their tool calls"
        )
        final = len(messages) >= 1 and dangling[-1] == len(messages) - 1
        for i in dangling:
            msg = dict(messages[i])
            msg.pop("tool_calls", None)
            content = msg.get("content")
            if final and i == dangling[-1]:
                msg["role"] = "assistant"
                msg["content"] = content or "I was about to run a command, but the request failed."
            elif not (content or "").strip():
                msg["role"] = "assistant"
                msg["content"] = "Continuing."
            messages[i] = msg

    # Group messages into turns, splitting on user messages.
    turns: list[dict] = []
    current: dict | None = None
    steps_by_id: dict[str, dict] = {}

    def _new_turn(user: str) -> dict:
        return {"user": user, "steps": [], "answer": "", "error": None}

    for msg in messages:
        role = msg.get("role")
        if role == "user":
            if current is not None:
                turns.append(current)
            current = _new_turn(msg.get("content") or "")
            steps_by_id = {}
        elif role == "assistant":
            if current is None:
                current = _new_turn("")  # assistant with no preceding user msg
            for tc in msg.get("tool_calls") or []:
                fn = (tc or {}).get("function") or {}
                step = {
                    "name": fn.get("name"),
                    "args": _parse_json_arg(fn.get("arguments"), {}),
                    "result": None,
                }
                tc_id = (tc or {}).get("id")
                if tc_id:
                    steps_by_id[tc_id] = step
                current["steps"].append(step)
            content = (msg.get("content") or "").strip()
            if content:
                current["answer"] = msg.get("content")
        elif role == "tool":
            step = steps_by_id.get(msg.get("tool_call_id"))
            if step is not None:
                step["result"] = _parse_json_arg(msg.get("content"), {})
            elif current is not None:
                warnings.append("orphan tool result ignored")
        # unknown roles are ignored

    if current is not None:
        turns.append(current)

    # Attach each error to the turn that produced it (by turn boundary), then
    # mark turns that produced no answer text as incomplete.
    for i, turn in enumerate(turns):
        if i in errors_by_turn:
            turn["error"] = errors_by_turn[i]
    for turn in turns:
        if not turn["answer"] and not turn["error"]:
            turn["incomplete"] = True

    started = records[0].get("ts") if records else None
    updated = records[-1].get("ts") if records else None

    return SessionPayload(
        session_id=header.get("session") or path.stem,
        model=header.get("model"),
        started_at=started,
        updated_at=updated,
        messages=messages,
        turns=turns,
        warnings=warnings,
    )
