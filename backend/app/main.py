"""The app: API under /api, the built PWA everywhere else."""

from __future__ import annotations

import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from . import categorize, config, records, storage
from .auth import User, admin_user
from .db import Conn, connect, get_db, migrate
from .embed import embedder
from .routes import auth as auth_routes
from .routes import receipts as receipt_routes
from .routes import reports as report_routes
from .routes import taxonomy as taxonomy_routes
from .worker import worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("receipts")


def startup() -> None:
    s = config.settings
    s.receipts_dir.mkdir(parents=True, exist_ok=True)
    fresh = not s.db_path.exists()
    conn = connect()
    try:
        migrate(conn)
        categorize.seed(conn)
        if fresh and any(storage.iter_sidecars()):
            # The folder is the record: a lost database rebuilds itself.
            log.info("no database but receipts on disk: rebuilding the index")
            records.reindex_all(conn)
    finally:
        conn.close()
    worker.start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup()
    yield
    worker.stop()


class Guard(BaseHTTPMiddleware):
    """Writes need the X-Requested-With header the app's fetch sends. A form
    on another site can't add it, so this closes CSRF on top of SameSite."""

    async def dispatch(self, request: Request, call_next):
        if (
            request.url.path.startswith("/api/")
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and request.headers.get("x-requested-with") != "fetch"
        ):
            return JSONResponse({"detail": "Missing X-Requested-With header"}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        return response


app = FastAPI(title="Receipts", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
app.add_middleware(Guard)
app.include_router(auth_routes.router)
app.include_router(receipt_routes.router)
app.include_router(taxonomy_routes.router)
app.include_router(report_routes.router)


@app.get("/api/health")
def health(conn: Conn = Depends(get_db)):
    return {
        "ok": True,
        "ocr": config.settings.ocr_enabled and bool(shutil.which("tesseract") or _tesseract_configured()),
        "pdf": bool(shutil.which("pdftotext")),
        "semantic": embedder.enabled and conn.vec_enabled,
        "model_loaded": embedder.loaded,
        "queue": worker.pending(),
    }


def _tesseract_configured() -> bool:
    import pytesseract

    return Path(pytesseract.pytesseract.tesseract_cmd).exists()


@app.post("/api/admin/reindex")
def reindex(_: User = Depends(admin_user), conn: Conn = Depends(get_db)):
    count = records.reindex_all(conn)
    for (rid,) in conn.execute("SELECT id FROM receipts WHERE status = 'queued'"):
        worker.ocr(rid)
    for (rid,) in conn.execute("SELECT id FROM receipts WHERE status != 'queued'"):
        worker.embed(rid)
    return {"receipts": count}


@app.get("/api/{rest:path}", include_in_schema=False)
def api_404(rest: str):
    return JSONResponse({"detail": "Not found"}, status_code=404)


@app.api_route("/{rest:path}", methods=["GET", "HEAD"], include_in_schema=False)
def spa(rest: str):
    """Built files as they are; any other path is the app's own route."""
    static = config.settings.static_dir.resolve()
    if rest:
        candidate = (static / rest).resolve()
        if static in candidate.parents and candidate.is_file():
            cache = "public, max-age=31536000, immutable" if rest.startswith("assets/") else "no-cache"
            return FileResponse(candidate, headers={"Cache-Control": cache})
    index = static / "index.html"
    if not index.exists():
        return JSONResponse({"detail": "The UI isn't built: run npm run build in frontend/"}, status_code=503)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
