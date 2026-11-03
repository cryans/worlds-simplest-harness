"""LLM client: one non-streaming call to DeepSeek."""

import httpx

from wsh.config import API_KEY, BASE_URL, MODEL
from wsh.tools import TOOLS


async def call_model(messages: list[dict]) -> dict:
    """One non-streaming call to DeepSeek. Returns the raw response JSON."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"model": MODEL, "messages": messages, "tools": TOOLS},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
