"""Sentence embeddings for meaning-based search: bge-small-en-v1.5 on ONNX,
run in the model helper process (modelhost.py), so it's only in memory while
someone is scanning or searching.
"""

from __future__ import annotations

import logging

from . import config
from .modelhost import host

log = logging.getLogger(__name__)

# bge models are trained with this instruction in front of short queries.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
# Give up on meaning-based search after this many failures in a row (a model
# that can't download, say); restarting the app tries again.
MAX_FAILURES = 3


class Embedder:
    def __init__(self) -> None:
        self._failures = 0

    @property
    def enabled(self) -> bool:
        return config.settings.semantic_search and self._failures < MAX_FAILURES

    @property
    def loaded(self) -> bool:
        return host.running

    def _run(self, texts: list[str]) -> list[list[float]]:
        if not self.enabled:
            return []
        try:
            out = host.call("embed", texts)
        except Exception as exc:  # noqa: BLE001 - search still works without vectors
            self._failures += 1
            log.error("embedding failed (%d/%d): %s", self._failures, MAX_FAILURES, exc)
            return []
        self._failures = 0
        return out

    def documents(self, texts: list[str]) -> list[list[float]]:
        return self._run(texts)

    def query(self, text: str) -> list[float] | None:
        out = self._run([QUERY_PREFIX + text])
        return out[0] if out else None

    def unload(self) -> None:
        host.stop()


embedder = Embedder()
