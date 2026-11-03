"""Dump the FastAPI OpenAPI schema to a file for openapi-typescript.

No server needed; importing the app only builds the app object.
Usage: uv run python dump_openapi.py <output-path>
"""
import json
import sys

from wsh.api.app import app

path = sys.argv[1] if len(sys.argv) > 1 else "openapi.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(app.openapi(), f, indent=2)
print(f"wrote {path}")
