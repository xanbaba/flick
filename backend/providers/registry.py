"""Provider construction (ARCHITECTURE.md section 17).

Full scope -- env-driven fallback chains (``gemini`` -> ``openai_compat``
-> ``do_gradient`` -> ``static``, each wrapped in a circuit breaker) --
is Dev A's ``backend/providers/`` territory and is out of scope for
this pass. But the knowledge layer (graph, retrieval, generation,
extraction, partner, onboarding, speller) has a hard constraint of its
own: "call the LLM through backend/providers/ only, never instantiate
a client directly." Those two facts only reconcile if some provider
module exists to call through.

This module wires just the guaranteed-offline last links: the static
LLM provider and the (real-or-hashing-trick) embedding provider. It
exposes the same singleton-getter shape the real registry will have,
so Dev A can drop ``llm_gemini.py`` etc. in front of ``StaticLLMProvider``
later without any caller in ``backend/app/services/`` changing.
"""

from __future__ import annotations

from .base import EmbeddingProvider, LLMProvider
from .embed_minilm import MiniLmEmbeddingProvider
from .llm_static import StaticLLMProvider

_llm: LLMProvider | None = None
_embedder: EmbeddingProvider | None = None


def get_llm_provider() -> LLMProvider:
    global _llm
    if _llm is None:
        _llm = StaticLLMProvider()
    return _llm


def get_embedding_provider() -> EmbeddingProvider:
    global _embedder
    if _embedder is None:
        _embedder = MiniLmEmbeddingProvider()
    return _embedder


def set_llm_provider(provider: LLMProvider) -> None:
    """Test/integration hook. Not used by production code paths."""
    global _llm
    _llm = provider


def set_embedding_provider(provider: EmbeddingProvider) -> None:
    """Test/integration hook. Not used by production code paths."""
    global _embedder
    _embedder = provider
