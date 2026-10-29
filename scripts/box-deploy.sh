#!/usr/bin/env bash
# The deploy zima-hub runs on the box (github.com/VashuChogada/zima-hub) when
# main moves: the same scripts/deploy.mjs as from a PC, copying to the receipts
# folder directly instead of over the share. If the server code changed, it
# touches data/.restart, and deploy/start.sh restarts the app on the new code.
set -euo pipefail

RECEIPTS_DIR="${RECEIPTS_DIR:-/media/Main-Storage/Data/receipts}"

(cd frontend && npm ci --no-audit --no-fund)

out="$(mktemp)"
RECEIPTS_SHARE="$RECEIPTS_DIR" node scripts/deploy.mjs | tee "$out"
if grep -q 'server code changed' "$out"; then
  touch "$RECEIPTS_DIR/data/.restart"
  echo "Asked receipts-app to restart."
fi
rm -f "$out"
