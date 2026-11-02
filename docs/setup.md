# Setup details

The README has the quick version. This covers the rest.

## What runs where

Two hub apps ([zima-hub](https://github.com/VashuChogada/zima-hub)), both from
standard images, both from this repo:

- `receipts` (`deploy/receipts/zima.json`) runs the app in `python:3.12-slim`,
  listening on 127.0.0.1:8491. Its build (`scripts/assemble.sh`) builds the
  web app and assembles the code into `deploy/receipts/out`, which the
  container mounts read-only at `/app`. Each start installs Tesseract (about
  25 s, since every deploy makes a new container); the Python packages and
  models live in the data folder, so they install once.
- `receipts-https` (`deploy/https/zima.json`) runs Caddy in `caddy:2-alpine`
  in front of it at `https://receipts.vashu.app:8493`, with a real Let's
  Encrypt certificate (below). It only answers devices on your home network.
  Both apps stay always on, because this Caddy talks to :8491 directly, which
  the hub's waker doesn't cover.

The hub also gives each app its own LAN port (`zima status`); the app itself
is on that one without HTTPS.

On the box:

```
Data/apps/receipts/data/
  receipts/   your scans and their .json files: back this up
  receipts.db search index, rebuilt from receipts/ if it's missing
  venv/       Python packages
  models/     the reading and search models
  cache/
Data/apps/receipts-https/data/   the certificate (lego/) and Caddy's own files
```

## Deploying

A push to `main` deploys both apps. Or `zima deploy receipts`. Each deploy
makes a new container, so a server-code change needs no extra restart.

## Problems

- **A receipt stays on "Reading", or the page shows a 502 error.** Check
  `zima logs apps/receipts`. On the very first start it can take a few
  minutes before the app is up.
- **Search misses something.** Settings → Rebuild index.
- **Dates read the wrong way round (04/03 vs 03/04).** Set `DATE_ORDER` in
  `deploy/receipts/zima.json`.

## Adding people

The first account you create is the admin. Add everyone else in Settings →
Household.

## Running it locally

On Windows you need Python 3.11+, Node 20+ and Tesseract
(`C:\Program Files\Tesseract-OCR`).

```bash
cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt
cd ../frontend && npm ci && npm run build
```

Then `scripts/dev-server.cmd` serves it on http://localhost:8491, with its
data in `backend/data-dev`. For working on the UI, `npm run dev` in
`frontend/` reloads as you edit.

On Linux or macOS:

```bash
cd backend && DATA_DIR=data-dev STATIC_DIR=../frontend/dist MODEL_CACHE=.models .venv/bin/python -m uvicorn app.main:app --port 8491
```

Tests: `python -m pytest` in `backend/`, `npm test` in `frontend/`.

## HTTPS for phones

Over plain HTTP everything works, and the scan button opens your phone's
camera app. HTTPS adds the live viewfinder inside the app and lets you
install it on the home screen. Phones need a certificate they already trust,
so `receipts-https` gets a real one from Let's Encrypt for
`receipts.vashu.app`, with nothing to install on any phone.

How it works: `deploy/https/run.sh` asks Let's Encrypt for the certificate
with a DNS challenge (a temporary TXT record in Cloudflare, made with the
`CLOUDFLARE_API_TOKEN` secret), checks for renewal daily, and reloads Caddy
when it renews. Nothing is exposed to the internet: `receipts.vashu.app` is a
DNS-only A record pointing at the box's LAN address, so it only works at home.

One-time setup:

1. Cloudflare → My Profile → API Tokens → create a token with
   *Zone / DNS / Edit* on `vashu.app` only.
2. `zima secret set receipts-https CLOUDFLARE_API_TOKEN` (it reads the value
   from stdin).
3. Cloudflare DNS: an `A` record `receipts` → `192.168.68.80`, DNS only (grey
   cloud). It takes precedence over the `*.vashu.app` tunnel record.

Then open `https://receipts.vashu.app:8493`. If a router blocks DNS answers
that point at private addresses ("DNS rebinding protection"), allow
`vashu.app` there. To try changes without using up Let's Encrypt's limits,
add `"ACME_SERVER": "https://acme-staging-v02.api.letsencrypt.org/directory"`
to the app's `vars`, and remove `/data/lego` afterwards.
