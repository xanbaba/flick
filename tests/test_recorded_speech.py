from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.services.speech import SpeechService
from backend.providers.base import Transcript
from backend.providers.stt_deepgram import DeepgramSTTProvider
from shared.config import EnvSettings, Settings, load_config


def test_recorded_audio_is_transcribed_without_starting_an_automatic_turn(monkeypatch) -> None:
    app = create_app(
        settings=Settings(
            config=load_config(), env=EnvSettings(_env_file=None, deepgram_api_key="test")
        )
    )
    orch = app.state.orchestrator
    orch.state = "IDLE"
    orch.speech.gate(False)
    transcribe = AsyncMock(return_value=Transcript(text="How are you", confidence=0.9))
    monkeypatch.setattr(DeepgramSTTProvider, "transcribe_recording", transcribe)
    client = TestClient(app)
    result = client.post(
        "/api/speech/transcribe",
        content=b"container audio",
        headers={"Content-Type": "audio/webm;codecs=opus"},
    )
    assert result.status_code == 200
    assert result.json() == {"text": "How are you", "confidence": 0.9}
    transcribe.assert_awaited_once_with(b"container audio", "audio/webm")
    assert orch.state == "IDLE"  # Browser submits the returned text through the existing route.
    orch.state = "SPEAKING"
    assert (
        client.post(
            "/api/speech/transcribe", content=b"audio", headers={"Content-Type": "audio/webm"}
        ).status_code
        == 409
    )
    assert transcribe.await_count == 1


def test_recording_validation_and_provider_failure_are_visible(monkeypatch) -> None:
    app = create_app(
        settings=Settings(
            config=load_config(), env=EnvSettings(_env_file=None, deepgram_api_key="test")
        )
    )
    app.state.orchestrator.state = "IDLE"
    app.state.orchestrator.speech.gate(False)
    client = TestClient(app)
    headers = {"Content-Type": "audio/ogg"}
    assert client.post("/api/speech/transcribe", content=b"").status_code == 415
    assert client.post("/api/speech/transcribe", content=b"", headers=headers).status_code == 422
    assert (
        client.post(
            "/api/speech/transcribe", content=b"x" * (10 * 1024 * 1024 + 1), headers=headers
        ).status_code
        == 413
    )
    transcribe = AsyncMock(side_effect=RuntimeError("private provider details"))
    monkeypatch.setattr(DeepgramSTTProvider, "transcribe_recording", transcribe)
    result = client.post("/api/speech/transcribe", content=b"audio", headers=headers)
    assert result.status_code == 502 and "private" not in result.text
    transcribe.side_effect = None
    transcribe.return_value = Transcript(text="noise", confidence=0.2)
    assert (
        client.post("/api/speech/transcribe", content=b"audio", headers=headers).status_code == 422
    )
    transcribe.return_value = Transcript(text="Try again", confidence=0.9)
    assert (
        client.post("/api/speech/transcribe", content=b"audio", headers=headers).status_code == 200
    )


async def test_manual_capture_does_not_open_backend_microphone(monkeypatch) -> None:
    import sounddevice

    unexpected = Mock(side_effect=AssertionError("Backend must not open microphone in manual mode"))
    monkeypatch.setattr(sounddevice, "RawInputStream", unexpected)
    speech = SpeechService(lambda t: None, automatic_capture=False)
    await speech.start()
    unexpected.assert_not_called()
    assert speech._stream is None
    await speech.stop()
