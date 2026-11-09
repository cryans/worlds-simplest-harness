"""sse(model): the single encoder turns an SseEvent into an SSE frame.

Pins the encoder contract only — the frame's `event:` name equals the model's
`type`, and the `data:` line parses back to the model's serialized fields. This is
*not* a substitute for the manual UI smoke (the browser renders the stream; that is
verified by a human, not this test).
"""

import json

import pytest

from wsh.models import (
    AnswerEvent,
    ErrorEvent,
    SessionEvent,
    SseEvent,
    StatusEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from wsh.sse import sse


@pytest.mark.parametrize(
    "model",
    [
        SessionEvent(type="session", session_id="abc"),
        StatusEvent(type="status", text="asking…"),
        ToolCallEvent(type="tool_call", name="bash", args={"c": 1}),
        ToolResultEvent(type="tool_result", name="bash", result={"exit_code": 0}),
        AnswerEvent(type="answer", session_id="abc", content="hi", messages=[]),
        ErrorEvent(type="error", message="boom"),
    ],
)
def test_sse_frames_event_model(model: SseEvent):
    frame = sse(model)
    lines = frame.rstrip("\n").split("\n")

    assert lines[0] == f"event: {model.type}"
    assert lines[1].startswith("data: ")

    payload = json.loads(lines[1][len("data: "):])
    # The payload carries the discriminator plus the model's own fields.
    assert payload["type"] == model.type
    assert payload == json.loads(model.model_dump_json())
