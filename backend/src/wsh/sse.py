"""Server-Sent Event encoding."""

import json


def sse(event: str, data: dict) -> str:
    """Encode one event for the browser as a Server-Sent Event.
    The type is repeated inside the JSON so the browser can parse it easily."""
    return f"event: {event}\ndata: {json.dumps({**data, 'type': event})}\n\n"
