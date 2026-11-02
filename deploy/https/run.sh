#!/bin/sh
# Starts the HTTPS front inside the stock caddy:2-alpine image: gets a Let's
# Encrypt certificate for $RECEIPTS_HOST by DNS challenge (Cloudflare, with the
# CLOUDFLARE_API_TOKEN secret), keeps it renewed, and runs Caddy with it.
# Needs no inbound access: the challenge is a DNS record, so the name can
# point at a private address.
set -eu

apk add --no-cache lego >/dev/null
export CLOUDFLARE_DNS_API_TOKEN="$CLOUDFLARE_API_TOKEN"
lego() {
  command lego --accept-tos --email "${ACME_EMAIL:-acme@vashu.app}" --dns cloudflare \
    --path /data/lego --domains "$RECEIPTS_HOST" ${ACME_SERVER:+--server "$ACME_SERVER"} "$@"
}

if [ ! -f "/data/lego/certificates/$RECEIPTS_HOST.crt" ]; then
  # A failure waits before the container restarts, to stay clear of Let's
  # Encrypt's failed-attempt limit.
  lego run || { echo "[run] certificate request failed"; sleep 300; exit 1; }
fi

(
  while sleep 86400; do
    lego renew --days 30 --renew-hook "caddy reload --config /app/Caddyfile --adapter caddyfile --address localhost:${CADDY_ADMIN_PORT:-2493}" || echo "[run] renewal failed"
  done
) &

exec caddy run --config /app/Caddyfile --adapter caddyfile
