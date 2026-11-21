# The receipts app's image, built by zima-hub on each deploy
# (deploy/receipts/zima.json). The context is deploy/receipts/out, which
# scripts/assemble.sh fills: app/, static/, requirements.txt, start.sh.
# Docker's classic builder: no RUN --mount or heredocs.
FROM python:3.12-slim

# Tesseract and poppler read receipts; GLib is for OpenCV (the OCR model).
# Debian trixie renamed GLib libglib2.0-0t64; older releases call it libglib2.0-0.
RUN set -eu; \
    apt-get update -qq; \
    glib=libglib2.0-0; \
    if apt-cache show libglib2.0-0t64 >/dev/null 2>&1; then glib=libglib2.0-0t64; fi; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng poppler-utils curl "$glib" >/dev/null; \
    rm -rf /var/lib/apt/lists/*

# Its own layer, so a deploy that doesn't change requirements.txt reuses it.
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /venv \
 && /venv/bin/pip install --no-cache-dir --disable-pip-version-check --progress-bar off -r /tmp/requirements.txt

COPY . /app
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 STATIC_DIR=/app/static
CMD ["sh", "/app/start.sh"]
