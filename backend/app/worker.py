"""The background worker: one job at a time, so OCR and the embedding model
never run side by side on a low-power box.

Jobs: ("ocr", id) reads a new upload; ("embed", id) refreshes a receipt's
vector after an edit. Unfinished OCR jobs are queued again at startup.
"""

from __future__ import annotations

import logging
import queue
import threading
import traceback

from . import categorize, config, ocr, parse, records, storage
from .db import session
from .embed import embedder

log = logging.getLogger(__name__)


class Worker:
    def __init__(self) -> None:
        self.jobs: queue.Queue[tuple[str, str, bool]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.current: tuple[str, str] | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="worker", daemon=True)
        self._thread.start()
        with session() as conn:
            for (rid,) in conn.execute("SELECT id FROM receipts WHERE status IN ('queued', 'processing') ORDER BY created_at"):
                self.ocr(rid)
            if conn.vec_enabled and embedder.enabled:
                for (rid,) in conn.execute("SELECT id FROM receipts WHERE embed_hash IS NULL AND status != 'queued'"):
                    self.embed(rid)

    def stop(self) -> None:
        self._stop.set()
        self.jobs.put(("stop", "", False))

    def ocr(self, receipt_id: str, overwrite: bool = False) -> None:
        self.jobs.put(("ocr", receipt_id, overwrite))

    def embed(self, receipt_id: str) -> None:
        self.jobs.put(("embed", receipt_id, False))

    def pending(self) -> int:
        return self.jobs.qsize()

    def _loop(self) -> None:
        while not self._stop.is_set():
            kind, rid, overwrite = self.jobs.get()
            if kind == "stop":
                self.jobs.task_done()
                return
            self.current = (kind, rid)
            try:
                if kind == "ocr":
                    run_ocr(rid, overwrite)
                    run_embed(rid)
                elif kind == "embed":
                    run_embed(rid)
            except records.NotFound:
                pass  # deleted while it waited
            except Exception:  # noqa: BLE001 - one bad receipt mustn't stop the queue
                log.error("job %s %s failed:\n%s", kind, rid, traceback.format_exc())
            finally:
                self.current = None
                self.jobs.task_done()

    def drain(self) -> None:
        """Tests: wait until every queued job is done."""
        self.jobs.join()


def run_ocr(receipt_id: str, overwrite: bool = False) -> None:
    with session() as conn:
        rec = records.get(conn, receipt_id)
        if not config.settings.ocr_enabled:
            records.set_status(conn, receipt_id, "review" if rec["status"] != "confirmed" else "confirmed",
                               "OCR is turned off; fill the fields in by hand")
            records.save_sidecar(conn, receipt_id)
            return
        if rec["status"] != "confirmed":
            records.set_status(conn, receipt_id, "processing")
        try:
            result = ocr.extract(storage.absolute(rec["file_path"]), rec["mime"])
        except Exception as exc:  # noqa: BLE001
            log.warning("OCR failed for %s: %s", receipt_id, exc)
            records.set_status(conn, receipt_id, "failed" if rec["status"] != "confirmed" else "confirmed", str(exc))
            records.save_sidecar(conn, receipt_id)
            return
        parsed = parse.parse_receipt(result.text, config.settings.date_order).to_dict()
        rules = categorize.load_rules(conn)
        rec = records.apply_ocr(conn, receipt_id, result.text, result.confidence, parsed, rules, overwrite)
        # A date and a total are enough to file it; anything less waits for a person.
        if config.settings.auto_file and rec["status"] == "review" and rec["txn_date"] and rec["total"] is not None:
            records.update(conn, receipt_id, {"status": "confirmed"}, None)


def run_embed(receipt_id: str) -> None:
    if not embedder.enabled:
        return
    with session() as conn:
        due = records.embedding_due(conn, receipt_id)
        if not due:
            return
        seq, text, digest = due
        vectors = embedder.documents([text])
        if vectors:
            records.store_embedding(conn, seq, vectors[0], digest)
            conn.commit()


worker = Worker()
