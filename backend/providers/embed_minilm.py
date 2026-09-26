"""Embedding provider (ARCHITECTURE.md SW-4, section 17).

Tries ``sentence-transformers``' ``all-MiniLM-L6-v2`` lazily, CPU
only, on first call. If it is not installed, or the model cannot be
loaded without network access, this degrades to a deterministic
offline hashing-trick embedding of the same dimensionality. Same
texts always hash to the same vector and shared tokens raise cosine
similarity, so retrieval and dedup are exercisable end-to-end with no
model download and no network call -- required for AGENTS.md section
8's "no network calls in tests" and for SW-13's degrade-not-raise
rule.
"""

from __future__ import annotations

import hashlib
import re
import threading

import numpy as np

from .base import EmbeddingProvider

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _hashing_trick_embed(texts: list[str], dim: int) -> np.ndarray:
    vectors = np.zeros((len(texts), dim), dtype=np.float64)
    for row, text in enumerate(texts):
        for token in _TOKEN_RE.findall(text.lower()):
            digest = int(hashlib.sha256(token.encode()).hexdigest(), 16)
            sign = 1.0 if (digest // dim) % 2 == 0 else -1.0
            vectors[row, digest % dim] += sign
        norm = np.linalg.norm(vectors[row])
        if norm > 0:
            vectors[row] /= norm
    return vectors


class MiniLmEmbeddingProvider(EmbeddingProvider):
    """Local, CPU, 384-dim (SW-4). Degrades to a hashing-trick placeholder."""

    name = "minilm"
    dim = 384

    def __init__(self) -> None:
        self._model = None
        self._load_attempted = False
        self._lock = threading.Lock()

    def _model_or_none(self):
        if self._load_attempted:
            return self._model
        with self._lock:
            if self._load_attempted:
                return self._model
            self._load_attempted = True
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
            except Exception:
                self._model = None
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float64)
        model = self._model_or_none()
        if model is not None:
            vectors = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
            return np.asarray(vectors, dtype=np.float64)
        return _hashing_trick_embed(texts, self.dim)
