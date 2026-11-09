"""Server-Sent Event encoding."""

from wsh.models import SseEvent


def sse(event: SseEvent) -> str:
    """Encode one event model for the browser as a Server-Sent Event.

    The frame `event:` name and the payload's `"type"` field both come from the
    model's discriminator (`event.type`), and `model_dump_json()` already emits the
    `"type"` field — so the two can't drift.
    """
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"
