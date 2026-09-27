import httpx
import pytest

from backend.providers.stt_deepgram import DeepgramSTTProvider


@pytest.mark.asyncio
async def test_raw_pcm_includes_format_and_preserves_transcript(monkeypatch) -> None:
    pcm = b"\x00\x00\x01\x00"

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.params["encoding"] == "linear16"
        assert request.url.params["sample_rate"] == "16000"
        assert request.url.params["channels"] == "1"
        assert request.headers["Authorization"] == "Token test-key"
        assert request.content == pcm
        return httpx.Response(
            200,
            json={
                "results": {
                    "channels": [
                        {"alternatives": [{"transcript": "hello there", "confidence": 0.93}]}
                    ]
                }
            },
        )

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        "backend.providers.stt_deepgram.httpx.AsyncClient",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handle), **kwargs),
    )
    result = await DeepgramSTTProvider("test-key").transcribe(pcm, 16000)
    assert result.text == "hello there"
    assert result.confidence == 0.93


async def test_containerized_recording_does_not_declare_raw_pcm(monkeypatch) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert not request.url.params
        assert request.headers["content-type"] == "audio/webm"
        assert request.content == b"recorded webm"
        return httpx.Response(
            200,
            json={
                "results": {
                    "channels": [
                        {"alternatives": [{"transcript": "How are you", "confidence": 0.95}]}
                    ]
                }
            },
        )

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: client_class(transport=httpx.MockTransport(handle), **kw)
    )
    result = await DeepgramSTTProvider("test").transcribe_recording(b"recorded webm", "audio/webm")
    assert result.text == "How are you"
