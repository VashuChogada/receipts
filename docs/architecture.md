# Architecture

```
Phone (PWA)                     Server (network_mode: host)
───────────                     ───────────────────────────────────────────────────────────
camera / gallery / PDF          receipts-caddy  :8490 http (and :8493 https, optional)
  │ lib/preprocess.ts             │  drops non-LAN and Cloudflare-tunnelled requests
  │  EXIF upright, ≤2000 px       ▼
  │  auto-crop (Otsu + row/col  receipts-app  127.0.0.1:8491  FastAPI, one uvicorn worker
  │  projections), grayscale,     ├─ POST /api/receipts ─► receipts/_inbox/<id>.jpg + <id>.json
  │  2/98 % levels, JPEG q0.85    │                        row status=queued, job queued
  └── multipart upload ──────────►├─ worker thread, one job at a time
                                  │    ocr.py   PDF text layer (pdftotext), else PP-OCRv6
                                  │             small in the model helper; Tesseract too
                                  │             when that reading lacks a total or date
                                  │    parse.py merchant, date/time, totals, payment, items
                                  │    merchants.py  alias table → fuzzy → known chains
                                  │    categorize.py rules → category + suggested tags
                                  │    embed.py bge-small-en-v1.5 (ONNX) → sqlite-vec
                                  │    date and total read? status=confirmed (AUTO_FILE),
                                  │    else status=review until someone fills them in
                                  ├─ confirmed ─► files move to
                                  │    receipts/YYYY/MM/<Category>/YYYY-MM-DD_<Merchant>_<Amount>_<id>.{jpg,json}
                                  └─ SQLite (WAL): receipts.db = index only
```

## The folder is the record

Each scan has a JSON details file beside it with every field, the OCR text,
what the parser read (`ocr.parsed`), tags with their HSA/donation/warranty
fields, attachments and an edit history. `receipts.db` is an index over those
files: if it's deleted the app rebuilds it at startup (`records.reindex_all`),
and Settings → Rebuild index does the same on demand. Deletes move files to
`receipts/_trash/`; nothing is erased by the app.

Changing a confirmed receipt's date, merchant, total or category moves its
files to the new name and folder; renaming a category moves every receipt in it.

## Search

`GET /api/receipts?q=…` runs `nlquery.parse` first: dates ("last month",
"in march", "q1 2025", "since 9/1"), amounts ("over $50", "between 20 and 40"),
merchants (fuzzy), categories, tags, payment, people ("mine", "sam's") and
status ("needs review", "unreimbursed") become filters, returned as chips.
Whatever is left is ranked by `search.rank`, Reciprocal Rank Fusion over:

| channel  | finds                                  | how                                     |
|----------|----------------------------------------|-----------------------------------------|
| words    | "groceries" → "grocery"                | FTS5, Porter stemming, bm25             |
| fuzzy    | "starbcks", "bananna"                  | trigram FTS5 candidates, rapidfuzz ≥ 80 |
| merchant | typo'd store names                     | rapidfuzz over known merchants          |
| meaning  | "coffee" → Starbucks, "lumber" → Home Depot | bge-small embeddings, cosine ≤ 0.45 |

The embedding model (33M parameters, 67 MB quantized ONNX) runs in the model
helper (below). `SEMANTIC_SEARCH=off` turns that channel off; everything else
still works.

## OCR and the model helper

PP-OCRv6 small (PaddleOCR's detection and recognition models, 31 MB of ONNX,
run through RapidOCR) does the reading. On the first three real receipts it
was tried on, it got 19 of 20 checked fields right where Tesseract got 14: it read
$251.00 where Tesseract read $31.00, and a 1.51 tax Tesseract made 1.61.
`ocr.lines_from_boxes` rebuilds the receipt's rows from its text boxes after
undoing the photo's tilt, so labels and right-aligned amounts stay together.
Tesseract remains as the fallback (`OCR_ENGINE=tesseract` makes it the only
engine).

Both models run in **one helper process** (`modelhost.py`), started by the
first scan or search and ended after `MODEL_IDLE_MINUTES` (5) without one.
Freeing ONNX models inside a long-running process never returns all their
memory to the OS; ending the process does.

## Accounts

Household accounts in `users`: argon2id hashes, 90-day sliding cookie sessions
(`HttpOnly`, `SameSite=Lax`, `Secure` over HTTPS), a failed-login throttle per
IP, and every write must carry `X-Requested-With: fetch` (CSRF). The first
account is the admin; it adds the others in Settings. Everyone sees every
receipt; `created_by` and the "mine" filter tell them apart.

## Memory

Measured on a desktop PC; expect similar on a small server.

| piece                     | idle    | in use                                   |
|---------------------------|---------|------------------------------------------|
| Caddy                     | ~20 MB  | ~30 MB                                   |
| app (FastAPI + worker)    | ~40-60 MB |                                        |
| model helper              | 0 (not running) | ~200 MB for search, ~310 MB peak while reading a receipt (one model at a time) |
| Tesseract (fallback only) | 0       | ~100 MB for a few seconds                |

A container's memory figure in `docker stats` or a NAS dashboard also counts
its file cache (the packages written on first start, files read since), which
the kernel takes back whenever anything needs it. `docker exec receipts-app grep -E
"^(anon|file) " /sys/fs/cgroup/memory.stat` splits real use (`anon`) from
cache (`file`).

## What isn't in the folder

Accounts and sessions live only in `receipts.db`. A rebuilt database has
every receipt but no users: the first visit asks for an admin again, and the
others are re-added in Settings. Rules and learned merchant names are also
database-only; the seeded defaults come back on their own.
