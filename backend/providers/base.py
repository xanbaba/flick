"""Provider ABCs (ARCHITECTURE.md section 17).

Only the two provider kinds the knowledge layer needs are defined
here: ``LLMProvider`` and ``EmbeddingProvider``. The STT/TTS ABCs and
the network-backed LLM links (``llm_gemini.py``, ``llm_openai_compat.py``,
``llm_do_gradient.py``) belong to Dev A's provider layer; see
``registry.py`` for the scope note on why a minimal scaffold lives
here instead of nothing at all.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class LLMProvider(ABC):
    """ARCHITECTURE.md section 17."""

    name: str

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 400,
        timeout: float = 6.0,
    ) -> str:
        """Return the raw completion text. Never raises; degrade instead."""


class EmbeddingProvider(ABC):
    """ARCHITECTURE.md section 17."""

    name: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an ``(len(texts), dim)`` float64 array. Never raises."""
