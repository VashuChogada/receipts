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
  in front of it at `https://<box>:8493`. It only
  answers devices on your home network. Both apps stay always on, because
  this Caddy talks to :8491 directly, which the hub's waker doesn't cover.

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
Data/apps/receipts-https/data/   Caddy's own files, including the local CA
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

## Optional: HTTPS for phones

You don't need this. Over plain HTTP everything works, and the scan button
opens your phone's camera app. HTTPS adds a live viewfinder inside the app and
lets you install it as a proper home-screen app. It also encrypts your
password on the Wi-Fi.

To turn it on:

1. `RECEIPTS_HOST` in `deploy/https/zima.json` is the box's IP address on your
   network; change it there if that changes.
2. On each phone, open `https://<server>:8493/ca.crt` and install the
   certificate.
   - iPhone: Settings → General → VPN & Device Management → install the
     profile, then Settings → General → About → Certificate Trust Settings →
     turn on "Caddy Local Authority".
   - Android: Settings → Security → Encryption & credentials → Install a
     certificate → CA certificate.
3. Open `https://<server>:8493` from then on.

Keep `Data/apps/receipts-https/data`: if it's lost, every phone has to install a new
certificate.
