#!/bin/sh
# How the receipts app starts in its image (deploy/receipts/Dockerfile, which
# zima-hub builds on each deploy with Tesseract, poppler and the Python
# packages in it). What's left to do here lives in the data folder, so it
# happens once:
#
#   the search model   /data/models, downloaded once (67 MB)
#   the OCR model      /data/models/rapidocr (31 MB, fetched from RapidOCR on first use)
set -eu

VENV=/venv
export MODEL_CACHE="${MODEL_CACHE:-/data/models}"

log() { echo "[start] $*"; }

if [ "${SEMANTIC_SEARCH:-on}" != "off" ] && ! ls "$MODEL_CACHE" 2>/dev/null | grep -q bge-small; then
  log "downloading the embedding model into $MODEL_CACHE"
  HF_HUB_OFFLINE=0 "$VENV/bin/python" -c \
    "from fastembed import TextEmbedding; TextEmbedding('${EMBED_MODEL:-BAAI/bge-small-en-v1.5}', cache_dir='$MODEL_CACHE')" \
    || log "model download failed; meaning-based search stays off until it succeeds"
fi

log "starting"
export HF_HUB_OFFLINE=1
cd /app
"$VENV/bin/uvicorn" app.main:app --host 127.0.0.1 --port "${APP_PORT:-8491}" --workers 1 \
  --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-server-header &
pid=$!

trap 'kill -TERM "$pid" 2>/dev/null' TERM INT
code=0
wait "$pid" || code=$?
while kill -0 "$pid" 2>/dev/null; do wait "$pid" || code=$?; done
exit "$code"
