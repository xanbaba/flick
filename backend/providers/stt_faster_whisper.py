"""faster-whisper local STT fallback (ARCHITECTURE.md section 17, SW-7).

CPU-only (SW-9): ``faster-whisper small`` via ctranslate2. The model
is loaded lazily on first use, not at import time -- constructing
this class is cheap even if the model weights are not cached and
there is no network to fetch them; the failure only surfaces (and
only then) on the first real ``transcribe()`` call, which is exactly
when registry.FallbackChain's circuit breaker needs to see it, so the
chain falls through to the manual link instead of hanging at startup.
"""

from __future__ import annotations

import asyncio
import threading

import numpy as np

from backend.providers.base import STTProvider, Transcript


class FasterWhisperSTTProvider(STTProvider):
    name = "faster_whisper"

    def __init__(self, model_size: str = "small") -> None:
        self._model_size = model_size
        self._model = None
        self._lock = threading.Lock()

    def _load_model(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        return self._model

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        return await asyncio.to_thread(self._transcribe_sync, pcm, sample_rate)

    def _transcribe_sync(self, pcm: bytes, sample_rate: int) -> Transcript:
        model = self._load_model()
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = model.transcribe(audio, language="en", vad_filter=False)
        segments = list(segments)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        if not text or not segments:
            return Transcript(text="", confidence=0.0)
        mean_log_prob = sum(s.avg_logprob for s in segments) / len(segments)
        confidence = float(min(max(np.exp(mean_log_prob), 0.0), 1.0))
        return Transcript(text=text, confidence=confidence)
