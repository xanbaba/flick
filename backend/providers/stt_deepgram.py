"""Deepgram STT provider (ARCHITECTURE.md section 10).

Batch call against Deepgram's pre-recorded audio endpoint: the raw
16-bit little-endian mono PCM captured by speech.py's VAD is sent with
explicit encoding and capture sample rate. No streaming -- the whole
utterance is already buffered by the time speech ends.
"""

from __future__ import annotations

import httpx

from backend.app.services.cost import outbound
from backend.providers.base import STTProvider, Transcript

_URL = "https://api.deepgram.com/v1/listen"


class DeepgramSTTProvider(STTProvider):
    name = "deepgram"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("deepgram requires an API key")
        self._api_key = api_key

    @outbound("stt", "Deepgram", "microphone audio")
    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "application/octet-stream",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _URL,
                headers=headers,
                params={"encoding": "linear16", "sample_rate": sample_rate, "channels": 1},
                content=pcm,
            )
        response.raise_for_status()
        payload = response.json()
        channels = payload.get("results", {}).get("channels") or []
        if not channels:
            raise RuntimeError("deepgram returned no channels")
        alternatives = channels[0].get("alternatives") or []
        if not alternatives:
            raise RuntimeError("deepgram channel has no alternatives")
        best = alternatives[0]
        return Transcript(
            text=best.get("transcript", ""),
            confidence=float(best.get("confidence", 0.0)),
        )
