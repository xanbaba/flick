"""Provider ABCs (ARCHITECTURE.md section 17).

Every provider kind the system needs: LLM, STT, TTS, and embeddings.
Callers never instantiate a concrete provider directly -- they go
through backend/providers/registry.py, which builds a fallback chain
per slot and hands back something that duck-types this same
interface (name + the one abstract method), so a chain is a drop-in
replacement for a single provider everywhere.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
from pydantic import BaseModel


class Transcript(BaseModel):
    """Result of an STTProvider.transcribe() call.

    Not part of shared/schemas.py's frozen wire contract (section 6)
    -- this never crosses a process boundary as its own message type,
    it is an in-process return value consumed by
    backend/app/services/speech.py, which decides whether it is real
    speech or noise (ARCHITECTURE.md section 15.1: confidence < 0.5 or
    fewer than two words is discarded).
    """

    text: str
    confidence: float  # 0..1
    language: str = "en"


class LLMProvider(ABC):
    """ARCHITECTURE.md section 17.

    A single provider may raise on failure (timeout, HTTP error,
    malformed response) -- that is how registry.FallbackChain and its
    circuit breaker detect a failed link and move to the next one.
    The chain itself never raises past its guaranteed-offline last
    link (StaticLLMProvider); individual links are not required to
    make that guarantee alone.
    """

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
        """Return the raw completion text, or raise on failure."""


class STTProvider(ABC):
    """ARCHITECTURE.md section 17. See LLMProvider's note on raising."""

    name: str

    @abstractmethod
    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        """Batch-transcribe 16-bit mono PCM, or raise on failure."""


class TTSProvider(ABC):
    """ARCHITECTURE.md section 17. See LLMProvider's note on raising."""

    name: str

    @abstractmethod
    async def synthesize(self, text: str, voice_id: str | None) -> bytes:
        """Return audio bytes (mp3/wav), or raise on failure."""


class EmbeddingProvider(ABC):
    """ARCHITECTURE.md section 17."""

    name: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an ``(len(texts), dim)`` float64 array. Never raises."""
