"""ElevenLabs TTS provider (ARCHITECTURE.md section 15.2, 17).

The user's own cloned voice, restored via ElevenLabs Instant Voice
Cloning (enrolled once by scripts/enroll_voice.py, out of scope
here). Streaming is not implemented -- section 15.2's runtime chain
already puts the cache in front of this link, so a full non-streamed
call only happens on a cache miss.
"""

from __future__ import annotations

import httpx

from backend.app.services.cost import outbound
from backend.providers.base import TTSProvider

_URL_TEMPLATE = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


class ElevenLabsTTSProvider(TTSProvider):
    name = "elevenlabs"

    def __init__(self, api_key: str, default_voice_id: str) -> None:
        if not api_key:
            raise ValueError("elevenlabs requires an API key")
        self._api_key = api_key
        self._default_voice_id = default_voice_id

    @outbound("tts", "ElevenLabs", "the sentence text only")
    async def synthesize(self, text: str, voice_id: str | None) -> bytes:
        resolved_voice_id = voice_id or self._default_voice_id
        if not resolved_voice_id:
            raise ValueError("elevenlabs requires a voice_id (none configured)")

        url = _URL_TEMPLATE.format(voice_id=resolved_voice_id)
        headers = {"xi-api-key": self._api_key, "Accept": "audio/mpeg"}
        body = {
            "text": text,
            "model_id": "eleven_flash_v2_5",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=body)
        response.raise_for_status()
        if not response.content:
            raise RuntimeError("elevenlabs returned no audio")
        return response.content
