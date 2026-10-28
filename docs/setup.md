# Setup details

The README has the quick version. This covers the rest.

## What runs where

Two containers, both from standard images (`deploy/compose.yaml`):

- `receipts-app` runs the app. On its first start it installs Tesseract and
  the Python packages into the data folder, so later starts take seconds.
- `receipts-caddy` is the web server in front of it, on port 8490. It only
  answers devices on your home network.

The code isn't baked into an image. `node scripts/deploy.mjs` builds the web
app and copies everything into `RECEIPTS_DIR`:

```
RECEIPTS_DIR/
  app/          the code (replaced on every deploy)
  config/       the web server's config (replaced on every deploy)
  data/
    receipts/   your scans and their .json files: back this up
    receipts.db search index, rebuilt from receipts/ if it's missing
    venv/       Python packages
    models/     the reading and search models
  caddy/        the web server's own files
```

Run `node scripts/deploy.mjs --dry-run` to see what a deploy would copy.

## ZimaOS or CasaOS

These take a compose file pasted into their dashboard and don't read `.env`.
The deploy script can print the compose file with your settings filled in.

1. Make a folder for Receipts on the server, for example
   `/media/Storage/Data/receipts`, and share it over SMB so your PC can reach
   it, for example as `//server/Storage/Data/receipts`.
2. In `.env`, set `RECEIPTS_DIR` to the server path and `RECEIPTS_SHARE` to
   the share path.
3. Run `node scripts/deploy.mjs` on your PC.
4. Run `node scripts/deploy.mjs --compose`, copy what it prints, and add it as
   a custom app in the dashboard.
5. When a deploy says the server code changed, restart the app from the
   dashboard.

If you change `.env` later, paste the new `--compose` output into the app's
settings.

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

## Problems

- **A receipt stays on "Reading", or the page shows a 502 error.** Check
  `docker logs receipts-app`. On the very first start it can take a few
  minutes before the app is up.
- **Search misses something.** Settings → Rebuild index.
- **Dates read the wrong way round (04/03 vs 03/04).** Set `DATE_ORDER` in
  `.env`.
- **A port is already in use.** Change `HTTP_PORT` or `APP_PORT` in `.env`.

## Optional: HTTPS for phones

You don't need this. Over plain HTTP everything works, and the scan button
opens your phone's camera app. HTTPS adds a live viewfinder inside the app and
lets you install it as a proper home-screen app. It also encrypts your
password on the Wi-Fi.

To turn it on:

1. In `.env`, set `RECEIPTS_HOST` to the server's IP address on your network,
   deploy again and restart the containers.
2. On each phone, open `http://<server>:8490/ca.crt` and install the
   certificate.
   - iPhone: Settings → General → VPN & Device Management → install the
     profile, then Settings → General → About → Certificate Trust Settings →
     turn on "Caddy Local Authority".
   - Android: Settings → Security → Encryption & credentials → Install a
     certificate → CA certificate.
3. Open `https://<server>:8493` from then on.

Keep the `caddy/` folder: if it's lost, every phone has to install a new
certificate.
