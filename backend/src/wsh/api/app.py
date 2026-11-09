"""FastAPI application assembly: `app`, CORS, and the OpenAPI schema override."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic import TypeAdapter

from wsh.models import SseEvent

app = FastAPI(title="World's Simplest Harness")

# Allow the Vite dev server (http://localhost:5173) to call us directly.
# (We ALSO set up a Vite proxy, so this is just a safety net.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def custom_openapi():
    """FastAPI can't discover SseEvent from a route (the chat body is a stream),
    so reflect it into `components.schemas` under a stable name. One generation
    path: the same `/openapi.json` that feeds `openapi-typescript`."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    comps = schema.setdefault("components", {}).setdefault("schemas", {})
    js = TypeAdapter(SseEvent).json_schema(ref_template="#/components/schemas/{model}")
    for name, member in js.pop("$defs", {}).items():
        comps[name] = member
    comps["SseEvent"] = js
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

# Importing the routes module binds the endpoints to `app`.
from wsh.api import routes  # noqa: E402, F401

# Importing a plugin registers it with the `wsh.plugins` seam. The smoke plugin
# lives on the sandbox branch; the seam itself has no smoke reference.
try:
    import wsh.plugins.smoke  # noqa: E402, F401
except ImportError:
    pass
