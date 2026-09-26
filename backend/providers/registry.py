"""Provider construction: env -> instance, with fallback chains.

ARCHITECTURE.md section 17: "registry.py builds a FallbackChain per
slot from env vars. Every provider is lazily constructed on first use
and wrapped in a circuit breaker: three consecutive failures marks it
unhealthy for 30 s and the chain skips it." Section 5 gives the exact
chains:

    LLM: gemini -> openai_compat -> do_gradient -> static
    STT: deepgram -> faster_whisper -> manual
    TTS: elevenlabs -> piper -> browser

"cache" is not a provider here -- section 15.2 puts the cache in
front of the TTS chain, and that lookup lives in
backend/app/services/voice.py, not in this module.

The last link in every chain is local, offline and never fails
(StaticLLMProvider, ManualSTTProvider, BrowserTTSProvider below).
That is what makes SW-13 real and acceptance test A6 possible: the
backend boots and serves a complete turn with an entirely empty
``.env``.

get_llm_provider() and get_embedding_provider() keep the exact
singleton-getter shape backend/app/services/graph.py already calls
through (see that module's own history) -- this registry now backs
them with real fallback chains instead of the minimal offline-only
scaffold, without any caller needing to change.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

from backend.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    STTProvider,
    Transcript,
    TTSProvider,
)
from backend.providers.embed_minilm import MiniLmEmbeddingProvider
from backend.providers.llm_gemini import GeminiLLMProvider
from backend.providers.llm_openai_compat import OpenAICompatLLMProvider
from backend.providers.llm_static import StaticLLMProvider
from backend.providers.stt_deepgram import DeepgramSTTProvider
from backend.providers.stt_faster_whisper import FasterWhisperSTTProvider
from backend.providers.tts_elevenlabs import ElevenLabsTTSProvider
from backend.providers.tts_piper import PiperTTSProvider
from shared.config import EnvSettings, get_settings
from shared.logging import get_logger

logger = get_logger(__name__)

FAILURE_THRESHOLD = 3
COOLDOWN_S = 30.0

T = TypeVar("T")


class CircuitBreaker:
    """Three consecutive failures -> unhealthy for COOLDOWN_S (section 17)."""

    def __init__(
        self, failure_threshold: int = FAILURE_THRESHOLD, cooldown_s: float = COOLDOWN_S
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_s = cooldown_s
        self._consecutive_failures = 0
        self._unhealthy_until = 0.0

    def is_healthy(self) -> bool:
        return time.monotonic() >= self._unhealthy_until

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._unhealthy_until = 0.0

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._unhealthy_until = time.monotonic() + self._cooldown_s


class ManualSTTProvider(STTProvider):
    """The STT chain's guaranteed-offline last link.

    There is nothing left to transcribe with -- this always returns
    an empty, zero-confidence Transcript, which speech.py's noise
    filter (confidence < 0.5 or fewer than two words, section 15.1)
    discards, leaving the orchestrator in IDLE. The operator uses
    POST /api/utterance (DEMO-4) instead.
    """

    name = "manual"

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        del pcm, sample_rate
        return Transcript(text="", confidence=0.0)


class BrowserTTSProvider(TTSProvider):
    """The TTS chain's guaranteed-offline last link (section 15.2).

    Returns no audio bytes: the browser's own SpeechSynthesis speaks
    the text client-side, triggered by a WS message. voice.py checks
    the chain's ``last_served_by`` to know when this happened, since
    b"" is a valid (empty) return, not a failure.
    """

    name = "browser"

    async def synthesize(self, text: str, voice_id: str | None) -> bytes:
        del text, voice_id
        return b""


class _FallbackChain(Generic[T]):
    """Shared plumbing behind the three public chain classes below.

    Tries each healthy link in order via ``method``, records success
    or failure against that link's circuit breaker, and falls through
    on any exception. The last link is contractually guaranteed not
    to raise, so this only raises if the chain itself is empty.
    """

    def __init__(
        self,
        links: list[object],
        method: Callable[[object], Callable[..., Awaitable[T]]],
    ) -> None:
        if not links:
            raise ValueError("a fallback chain needs at least one link")
        self._links = links
        self._method = method
        self._breakers = [CircuitBreaker() for _ in links]
        self.last_served_by: str | None = None

    def health(self) -> dict[str, bool]:
        return {
            link.name: breaker.is_healthy()
            for link, breaker in zip(self._links, self._breakers, strict=True)
        }

    async def call(self, *args: object, **kwargs: object) -> T:
        last_exc: Exception | None = None
        for link, breaker in zip(self._links, self._breakers, strict=True):
            if not breaker.is_healthy():
                continue
            try:
                result = await self._method(link)(*args, **kwargs)
            except Exception as exc:
                breaker.record_failure()
                last_exc = exc
                logger.warning("provider.link_failed", provider=link.name, error=str(exc))
                continue
            breaker.record_success()
            self.last_served_by = link.name
            return result
        raise RuntimeError(f"fallback chain exhausted: {last_exc}") from last_exc


class LLMFallbackChain(LLMProvider):
    name = "llm_chain"

    def __init__(self, links: list[LLMProvider]) -> None:
        self._chain: _FallbackChain[str] = _FallbackChain(links, lambda p: p.complete)

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 400,
        timeout: float = 6.0,
    ) -> str:
        return await self._chain.call(
            system, user, json_mode=json_mode, max_tokens=max_tokens, timeout=timeout
        )

    def health(self) -> dict[str, bool]:
        return self._chain.health()

    @property
    def last_served_by(self) -> str | None:
        return self._chain.last_served_by


class STTFallbackChain(STTProvider):
    name = "stt_chain"

    def __init__(self, links: list[STTProvider]) -> None:
        self._chain: _FallbackChain[Transcript] = _FallbackChain(links, lambda p: p.transcribe)

    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript:
        return await self._chain.call(pcm, sample_rate)

    def health(self) -> dict[str, bool]:
        return self._chain.health()

    @property
    def last_served_by(self) -> str | None:
        return self._chain.last_served_by


class TTSFallbackChain(TTSProvider):
    name = "tts_chain"

    def __init__(self, links: list[TTSProvider]) -> None:
        self._chain: _FallbackChain[bytes] = _FallbackChain(links, lambda p: p.synthesize)

    async def synthesize(self, text: str, voice_id: str | None) -> bytes:
        return await self._chain.call(text, voice_id)

    def health(self) -> dict[str, bool]:
        return self._chain.health()

    @property
    def last_served_by(self) -> str | None:
        return self._chain.last_served_by


# --------------------------------------------------------------------------
# Chain builders: env -> instance. A link is omitted entirely if its
# key/config is absent (section 5: "skipped if its key is absent").
# --------------------------------------------------------------------------


def _build_llm_chain(env: EnvSettings) -> LLMFallbackChain:
    links: list[LLMProvider] = []
    if env.gemini_api_key:
        links.append(GeminiLLMProvider(env.gemini_api_key, env.gemini_model))
    if env.openai_compat_base_url and env.openai_compat_model:
        links.append(
            OpenAICompatLLMProvider(
                "openai_compat",
                env.openai_compat_base_url,
                env.openai_compat_model,
                env.openai_compat_api_key,
            )
        )
    if env.do_gradient_base_url and env.do_gradient_model:
        links.append(
            OpenAICompatLLMProvider(
                "do_gradient",
                env.do_gradient_base_url,
                env.do_gradient_model,
                env.do_gradient_api_key,
            )
        )
    links.append(StaticLLMProvider())
    return LLMFallbackChain(links)


def _build_stt_chain(env: EnvSettings) -> STTFallbackChain:
    links: list[STTProvider] = []
    if env.deepgram_api_key:
        links.append(DeepgramSTTProvider(env.deepgram_api_key))
    links.append(FasterWhisperSTTProvider())
    links.append(ManualSTTProvider())
    return STTFallbackChain(links)


def _build_tts_chain(env: EnvSettings) -> TTSFallbackChain:
    links: list[TTSProvider] = []
    if env.elevenlabs_api_key:
        links.append(ElevenLabsTTSProvider(env.elevenlabs_api_key, env.elevenlabs_voice_id))
    if env.piper_model_path:
        try:
            links.append(PiperTTSProvider(env.piper_model_path))
        except ValueError as exc:
            logger.info("tts_piper.unavailable_at_startup", reason=str(exc))
    links.append(BrowserTTSProvider())
    return TTSFallbackChain(links)


# --------------------------------------------------------------------------
# Singletons, built lazily on first use (section 17).
# --------------------------------------------------------------------------

_llm: LLMProvider | None = None
_stt: STTProvider | None = None
_tts: TTSProvider | None = None
_embedder: EmbeddingProvider | None = None


def get_llm_provider() -> LLMProvider:
    global _llm
    if _llm is None:
        _llm = _build_llm_chain(get_settings().env)
    return _llm


def get_stt_provider() -> STTProvider:
    global _stt
    if _stt is None:
        _stt = _build_stt_chain(get_settings().env)
    return _stt


def get_tts_provider() -> TTSProvider:
    global _tts
    if _tts is None:
        _tts = _build_tts_chain(get_settings().env)
    return _tts


def get_embedding_provider() -> EmbeddingProvider:
    global _embedder
    if _embedder is None:
        _embedder = MiniLmEmbeddingProvider()
    return _embedder


def set_llm_provider(provider: LLMProvider) -> None:
    """Test/integration hook. Not used by production code paths."""
    global _llm
    _llm = provider


def set_stt_provider(provider: STTProvider) -> None:
    """Test/integration hook. Not used by production code paths."""
    global _stt
    _stt = provider


def set_tts_provider(provider: TTSProvider) -> None:
    """Test/integration hook. Not used by production code paths."""
    global _tts
    _tts = provider


def set_embedding_provider(provider: EmbeddingProvider) -> None:
    """Test/integration hook. Not used by production code paths."""
    global _embedder
    _embedder = provider


def health_snapshot() -> dict[str, dict[str, bool]]:
    """Provider health for sys.status.providers (section 6.6)."""
    snapshot: dict[str, dict[str, bool]] = {}
    if isinstance(_llm, LLMFallbackChain):
        snapshot["llm"] = _llm.health()
    if isinstance(_stt, STTFallbackChain):
        snapshot["stt"] = _stt.health()
    if isinstance(_tts, TTSFallbackChain):
        snapshot["tts"] = _tts.health()
    return snapshot
