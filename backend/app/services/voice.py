"""TTS with the cache in front of the chain (ARCHITECTURE.md section 15.2).

Runtime order: cache (SHA-256 of the sentence -> data/audio_cache/{hash}.mp3,
zero network on a hit) -> the registry's TTSProvider chain
(elevenlabs -> piper -> browser). ``voice`` on the result reports
which tier actually served the request, mirrored into conv.spoken
(section 6.6) so the dashboard shows it, including when it was cached.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from pydantic import BaseModel

from backend.providers.registry import get_tts_provider
from shared.logging import get_logger

logger = get_logger(__name__)


class SpokenResult(BaseModel):
    """Backs the conv.spoken WS event's payload (section 6.6)."""

    text: str
    audio: bytes
    voice: str  # "cache" | provider name ("elevenlabs", "piper", "browser")
    cached: bool
    latency_ms: float


class VoiceService:
    def __init__(
        self, cache_dir: str, *, cache_first: bool = True, voice_id: str | None = None
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_first = cache_first
        self._voice_id = voice_id
        if self._cache_first:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, text: str) -> Path:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.mp3"

    async def speak(self, text: str) -> SpokenResult:
        start = time.monotonic()

        if self._cache_first:
            cache_path = self._cache_path(text)
            if cache_path.is_file():
                audio = cache_path.read_bytes()
                return SpokenResult(
                    text=text,
                    audio=audio,
                    voice="cache",
                    cached=True,
                    latency_ms=(time.monotonic() - start) * 1000,
                )

        tts = get_tts_provider()
        audio = await tts.synthesize(text, self._voice_id)
        served_by = getattr(tts, "last_served_by", None) or tts.name

        if audio and self._cache_first:
            self._cache_path(text).write_bytes(audio)

        return SpokenResult(
            text=text,
            audio=audio,
            voice=served_by,
            cached=False,
            latency_ms=(time.monotonic() - start) * 1000,
        )
