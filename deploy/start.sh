#!/bin/sh
# How receipts-app starts inside the stock python:3.12-slim image
# (deploy/compose.yaml). Nothing is built into an image: the code is the
# folder scripts/deploy.mjs copies to $RECEIPTS_DIR/app, and this sets up what
# the code needs on first start:
#
#   Tesseract and poppler   apt, once per container (a few hundred MB, ~1 min)
#   Python packages         a venv in /data/venv, again only when
#                           requirements.txt changes (~2 min the first time)
#   the search model        /data/models, downloaded once (67 MB)
#   the OCR model           /data/models/rapidocr, copied by the deploy (31 MB)
#
# After that a restart takes seconds.
set -eu

APP=/app
VENV=/data/venv
export MODEL_CACHE="${MODEL_CACHE:-/data/models}"

log() { echo "[start] $*"; }

# The system packages, installed once per container. A change to the list
# changes the marker's name, so an existing container picks up additions.
# Nothing here may stop the app from starting: a failure is logged, the app
# starts with what it has, and the next start tries again.
PACKAGES="tesseract-ocr tesseract-ocr-eng poppler-utils curl"
marker="/var/lib/receipts-apt-$(echo "$PACKAGES glib" | sha1sum | cut -c1-12)"
if [ ! -f "$marker" ]; then
  log "installing system packages: $PACKAGES"
  if apt-get update -qq; then
    # GLib for OpenCV (used by the OCR model). Debian trixie renamed it
    # libglib2.0-0t64; older releases call it libglib2.0-0.
    glib=libglib2.0-0
    apt-cache show libglib2.0-0t64 >/dev/null 2>&1 && glib=libglib2.0-0t64
    # shellcheck disable=SC2086
    if DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends $PACKAGES "$glib" >/dev/null; then
      touch "$marker"
    else
      log "WARNING: apt couldn't install the packages; trying again on the next start"
    fi
  else
    log "WARNING: apt-get update failed (no internet?); trying again on the next start"
  fi
  rm -rf /var/lib/apt/lists/*
fi

want="$(sha1sum "$APP/requirements.txt" | cut -d' ' -f1)"
if [ ! -f "$VENV/.requirements-$want" ]; then
  log "installing Python packages into $VENV (a few minutes)"
  [ -x "$VENV/bin/python" ] || python -m venv "$VENV"
  if "$VENV/bin/pip" install --no-cache-dir --disable-pip-version-check --progress-bar off -r "$APP/requirements.txt"; then
    rm -f "$VENV"/.requirements-*
    touch "$VENV/.requirements-$want"
  else
    log "WARNING: pip failed; starting with the packages already installed, trying again on the next start"
  fi
fi

if [ "${SEMANTIC_SEARCH:-on}" != "off" ] && ! ls "$MODEL_CACHE" 2>/dev/null | grep -q bge-small; then
  log "downloading the embedding model into $MODEL_CACHE"
  HF_HUB_OFFLINE=0 "$VENV/bin/python" -c \
    "from fastembed import TextEmbedding; TextEmbedding('${EMBED_MODEL:-BAAI/bge-small-en-v1.5}', cache_dir='$MODEL_CACHE')" \
    || log "model download failed; meaning-based search stays off until it succeeds"
fi

log "starting"
export HF_HUB_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1 STATIC_DIR="$APP/static"
cd "$APP"
"$VENV/bin/uvicorn" app.main:app --host 127.0.0.1 --port "${APP_PORT:-8491}" --workers 1 \
  --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-server-header &
pid=$!

# A deploy that changes the server code touches /data/.restart
# (scripts/box-deploy.sh): uvicorn stops and this script starts over, so new
# packages are installed and the new code loads, without restarting the
# container.
stamp() { stat -c %Y /data/.restart 2>/dev/null || echo 0; }
(
  seen="$(stamp)"
  while kill -0 "$pid" 2>/dev/null; do
    sleep 2
    if [ "$(stamp)" != "$seen" ]; then
      log "new server code deployed: restarting"
      touch /tmp/receipts-restart
      kill -TERM "$pid"
      exit 0
    fi
  done
) &

trap 'kill -TERM "$pid" 2>/dev/null' TERM INT
code=0
wait "$pid" || code=$?
while kill -0 "$pid" 2>/dev/null; do wait "$pid" || code=$?; done

if [ -f /tmp/receipts-restart ]; then
  rm -f /tmp/receipts-restart
  exec sh "$APP/start.sh"
fi
exit "$code"
