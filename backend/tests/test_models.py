"""Model-boundary smoke: the SSE union discriminates on `type`."""

import pytest
from pydantic import TypeAdapter, ValidationError

from wsh.models import SseEvent


def test_sse_event_discriminates_on_type():
    adapter = TypeAdapter(SseEvent)
    event = adapter.validate_python({"type": "status", "text": "asking the model…"})
    assert event.type == "status"
    assert event.text == "asking the model…"
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "not-an-event"})
