#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/backend"
uv run python dump_openapi.py "$ROOT/frontend/schema.json"
cd "$ROOT/frontend"
pnpm exec openapi-typescript schema.json -o src/api-types.ts
