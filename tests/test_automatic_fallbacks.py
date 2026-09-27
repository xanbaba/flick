"""Exercise registry wiring and real services with unavailable provider boundaries."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from backend.app.services.voice import VoiceService
from backend.providers import registry
from backend.providers.base import Transcript
from backend.providers.embed_minilm import MiniLmEmbeddingProvider
from shared.config import EnvSettings


@pytest.mark.parametrize("piper_state", ["available", "missing_binary", "missing_model", "fails"])
async def test_elevenlabs_failure_uses_piper_or_browser_then_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, piper_state: str
) -> None:
    from backend.providers import tts_piper

    model = tmp_path / "voice.onnx"
    if piper_state != "missing_model":
        model.write_bytes(b"test model boundary")
    monkeypatch.setattr(
        tts_piper.shutil,
        "which",
        lambda binary: None if piper_state == "missing_binary" else binary,
    )
    cloud = AsyncMock(side_effect=RuntimeError("cloud unavailable"))
    monkeypatch.setattr(registry.ElevenLabsTTSProvider, "synthesize", cloud)
    calls: list[str] = []

    async def subprocess(*args: str, **kwargs: object) -> SimpleNamespace:
        calls.append(args[0])
        output = Path(args[args.index("--output_file") + 1])

        async def communicate(text: bytes) -> tuple[bytes, bytes]:
            assert text == b"call Elena"
            if piper_state == "available":
                output.write_bytes(b"RIFFtest wave data")
            return b"", b"unavailable" if piper_state == "fails" else b""

        return SimpleNamespace(communicate=communicate, returncode=int(piper_state == "fails"))

    monkeypatch.setattr(tts_piper.asyncio, "create_subprocess_exec", subprocess)
    chain = registry._build_tts_chain(
        EnvSettings(_env_file=None, elevenlabs_api_key="test", piper_model_path=str(model))
    )
    monkeypatch.setattr(registry, "_tts", chain)
    voice = VoiceService(str(tmp_path / "audio"))
    first = await voice.speak("call Elena")
    assert cloud.await_count == 1
    assert first.voice == ("piper" if piper_state == "available" else "browser")
    assert bool(first.audio) == (piper_state == "available")
    assert len(calls) == int(piper_state in {"available", "fails"})
    if first.audio:
        second = await voice.speak("call Elena")
        assert second.cached and second.voice == "cache" and second.audio == first.audio
        assert cloud.await_count == 1 and len(calls) == 1


@pytest.mark.parametrize("local_available", [True, False])
async def test_deepgram_failure_uses_whisper_or_manual(
    monkeypatch: pytest.MonkeyPatch, local_available: bool
) -> None:
    from backend.providers.stt_faster_whisper import FasterWhisperSTTProvider

    cloud = AsyncMock(side_effect=RuntimeError("cloud unavailable"))
    monkeypatch.setattr(registry.DeepgramSTTProvider, "transcribe", cloud)
    model = Mock()
    model.transcribe.return_value = ([SimpleNamespace(text="hello Elena", avg_logprob=-0.1)], None)
    loader = Mock(
        return_value=model, side_effect=None if local_available else RuntimeError("missing")
    )
    monkeypatch.setattr(FasterWhisperSTTProvider, "_load_model", loader)
    chain = registry._build_stt_chain(EnvSettings(_env_file=None, deepgram_api_key="test"))
    result = await chain.transcribe(b"\0\0" * 20, 16000)
    assert cloud.await_count == 1 and loader.call_count == 1
    if local_available:
        assert result.text == "hello Elena" and result.confidence > 0.5
        assert chain.last_served_by == "faster_whisper"
    else:
        assert result == Transcript(text="", confidence=0)
        assert chain.last_served_by == "manual"


def test_minilm_load_failure_uses_stable_deterministic_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructor = Mock(side_effect=RuntimeError("model unavailable"))
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=constructor)
    )
    provider = MiniLmEmbeddingProvider()
    first = provider.embed(["mint tea", "mint tea", "blue chair"])
    assert first.shape == (3, 384) and np.isfinite(first).all()
    np.testing.assert_array_equal(first[0], first[1])
    assert not np.array_equal(first[0], first[2])
    np.testing.assert_array_equal(first, provider.embed(["mint tea", "mint tea", "blue chair"]))
    assert constructor.call_count == 1
