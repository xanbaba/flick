"""Exercise the speech request without calling the external provider."""

import json

import httpx
import pytest

from backend.providers.tts_elevenlabs import ElevenLabsTTSProvider


async def test_flash_speech_request_returns_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    audio = b"test audio response"

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/text-to-speech/test-voice"
        assert request.headers["xi-api-key"] == "test-key"
        body = json.loads(request.content)
        assert body["model_id"] == "eleven_flash_v2_5"
        assert body["text"] == "Hello"
        return httpx.Response(200, content=audio)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    provider = ElevenLabsTTSProvider("test-key", "test-voice")
    assert await provider.synthesize("Hello", None) == audio
