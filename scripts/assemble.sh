#!/usr/bin/env bash
# The "build" of deploy/receipts/zima.json, run by zima-hub in that folder: builds the UI and
# assembles deploy/receipts/out, the folder its Dockerfile builds from.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/deploy/receipts/out"

(cd "$ROOT/frontend" && npm ci --no-audit --no-fund && npm run build)

rm -rf "$OUT"
mkdir -p "$OUT/app"
cp -r "$ROOT/backend/app/." "$OUT/app/"
find "$OUT/app" -name __pycache__ -prune -exec rm -rf {} +
cp "$ROOT/backend/requirements.txt" "$ROOT/deploy/receipts/start.sh" "$OUT/"
cp -r "$ROOT/frontend/dist" "$OUT/static"
