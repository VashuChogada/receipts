"""The heavy models live in a helper process that exits when idle.

PP-OCRv6 (reading receipts) and bge-small (meaning-based search) both run on
ONNX Runtime and together hold ~250 MB while loaded. Freeing them inside the
app process never gives all of that back to the OS, so they run in a child
process instead: started on the first scan or search, ended after
MODEL_IDLE_MINUTES without one. The app itself then idles at ~60 MB.

The child handles one request at a time, like the worker that feeds it, and
holds one model at a time: OCR on a receipt photo peaks near 300 MB, and with
the search model loaded beside it the helper went past the container's cap
and was killed. Reloading a model takes well under a second.
"""

from __future__ import annotations

import ctypes
import gc
import logging
import multiprocessing as mp
import sys
import threading
import time
from pathlib import Path

from . import config

log = logging.getLogger(__name__)


class ModelHost:
    def __init__(self) -> None:
        self._proc: mp.process.BaseProcess | None = None
        self._conn = None
        self._lock = threading.Lock()
        self._last = 0.0
        self._reaper: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def call(self, op: str, *args, timeout: float = 600):
        with self._lock:
            if not self.running:
                self._start()
            self._last = time.monotonic()
            try:
                self._conn.send((op, args))
                if not self._conn.poll(timeout):
                    raise TimeoutError(f"{op} took over {timeout:.0f}s")
                ok, value = self._conn.recv()
            except (EOFError, BrokenPipeError, ConnectionError, OSError, TimeoutError) as exc:
                # Most likely killed for memory. Start fresh next time.
                self._kill()
                raise RuntimeError(f"the model helper stopped: {exc}") from exc
            finally:
                self._last = time.monotonic()
        if not ok:
            raise RuntimeError(value)
        return value

    def stop(self) -> None:
        with self._lock:
            self._kill()

    def _start(self) -> None:
        s = config.settings
        opts = {
            "model_cache": str(s.model_cache),
            "embed_model": s.embed_model,
            "threads": s.model_threads,
        }
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self._proc = ctx.Process(target=_serve, args=(child, opts), name="receipts-models", daemon=True)
        self._proc.start()
        child.close()
        self._conn = parent
        log.info("model helper started (pid %s)", self._proc.pid)
        if not (self._reaper and self._reaper.is_alive()):
            self._reaper = threading.Thread(target=self._reap, name="model-reaper", daemon=True)
            self._reaper.start()

    def _kill(self) -> None:
        if self._proc is None:
            return
        try:
            self._conn.send(("exit", ()))
        except Exception:  # noqa: BLE001 - already gone
            pass
        self._proc.join(3)
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(3)
        log.info("model helper stopped")
        self._proc = None
        self._conn = None

    def _reap(self) -> None:
        while True:
            idle = config.settings.model_idle_minutes * 60
            time.sleep(min(30.0, max(idle / 4, 0.5)))
            with self._lock:
                if self._proc is None:
                    return
                if time.monotonic() - self._last >= idle:
                    self._kill()
                    return


host = ModelHost()


# --- the child process --------------------------------------------------------


def _serve(conn, opts: dict) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s models: %(message)s")
    models: dict = {}
    while True:
        try:
            op, args = conn.recv()
        except (EOFError, KeyboardInterrupt):
            return
        if op == "exit":
            return
        try:
            if op == "embed":
                value = [v.tolist() for v in _embedder(models, opts).embed(list(args[0]), batch_size=8)]
            elif op == "ocr":
                value = _ocr(models, opts, args[0])
            elif op == "ping":
                value = "pong"
            else:
                raise ValueError(f"unknown op {op}")
            conn.send((True, value))
        except Exception as exc:  # noqa: BLE001 - report it, keep serving
            conn.send((False, f"{type(exc).__name__}: {exc}"))


def _only(models: dict, keep: str) -> None:
    """Drop every model but `keep`, and give the memory back."""
    dropped = [k for k in models if k != keep]
    for k in dropped:
        del models[k]
    if dropped:
        gc.collect()
        if sys.platform.startswith("linux"):
            try:
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except OSError:
                pass


def _embedder(models: dict, opts: dict):
    _only(models, "embed")
    if "embed" not in models:
        from fastembed import TextEmbedding

        started = time.monotonic()
        Path(opts["model_cache"]).mkdir(parents=True, exist_ok=True)
        models["embed"] = TextEmbedding(model_name=opts["embed_model"], cache_dir=opts["model_cache"], threads=opts["threads"])
        logging.info("embedding model loaded in %.1fs", time.monotonic() - started)
    return models["embed"]


def _ocr(models: dict, opts: dict, path: str) -> dict:
    _only(models, "ocr")
    if "ocr" not in models:
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import LangDet, LangRec, ModelType, OCRVersion

        started = time.monotonic()
        root = Path(opts["model_cache"]) / "rapidocr"
        root.mkdir(parents=True, exist_ok=True)
        models["ocr"] = RapidOCR(params={
            "Global.model_root_dir": str(root),
            "Global.log_level": "error",
            # Receipts arrive upright (the phone fixed that), and 1280 px on the
            # long side reads them just as well with ~40 MB less at the peak.
            "Global.use_cls": False,
            "Global.max_side_len": 1280,
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Det.model_type": ModelType.SMALL,
            "Rec.model_type": ModelType.SMALL,
            "Det.lang_type": LangDet.EN,
            "Rec.lang_type": LangRec.EN,
            "EngineConfig.onnxruntime.intra_op_num_threads": opts["threads"],
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        })
        logging.info("OCR model loaded in %.1fs", time.monotonic() - started)
    result = models["ocr"](path)
    if not result.txts:
        return {"boxes": [], "texts": [], "scores": []}
    return {
        "boxes": [[[float(x), float(y)] for x, y in box] for box in result.boxes],
        "texts": list(result.txts),
        "scores": [float(s) for s in result.scores],
    }
