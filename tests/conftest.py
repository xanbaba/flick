"""Tests never load credentials, download models, or call a live provider."""

from __future__ import annotations

from unittest.mock import AsyncMock

import numpy as np
import pytest

from backend.app.services.speech import SpeechService
from backend.providers import registry
from backend.providers.base import EmbeddingProvider
from backend.providers.embed_minilm import _hashing_trick_embed
from backend.providers.llm_static import StaticLLMProvider
from shared.config import EnvSettings, get_settings


class TestEmbeddings(EmbeddingProvider):
    __test__ = False
    name = "test_hash"
    dim = 384

    def embed(self, texts: list[str]) -> np.ndarray:
        return _hashing_trick_embed(texts, self.dim)


@pytest.fixture(autouse=True)
def offline_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(EnvSettings.model_config, "env_file", None)
    for field in EnvSettings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setattr(registry, "_llm", StaticLLMProvider())
    monkeypatch.setattr(registry, "_embedder", TestEmbeddings())
    monkeypatch.setattr(registry, "_stt", registry.ManualSTTProvider())
    monkeypatch.setattr(registry, "_tts", registry.BrowserTTSProvider())
    monkeypatch.setattr(SpeechService, "start", AsyncMock())
    monkeypatch.setattr(SpeechService, "stop", AsyncMock())
    get_settings.cache_clear()
