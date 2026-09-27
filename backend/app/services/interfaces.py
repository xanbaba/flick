"""Internal contracts shared by the orchestrator and concrete memory services."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from typing import Protocol

from backend.app.services.extraction import ExtractionResult
from backend.app.services.generation import CandidateResult, IntentResult
from backend.app.services.onboarding import BloomBatch
from backend.app.services.partner import PartnerIdentification
from backend.app.services.retrieval import RetrievalResult


class RetrievalServiceProtocol(Protocol):
    def retrieve(
        self, query_text: str, partner_id: str | None = None
    ) -> RetrievalResult | Awaitable[RetrievalResult]: ...


class GenerationServiceProtocol(Protocol):
    """ARCHITECTURE.md section 12.1-12.2. Calls LLMProvider.complete()

    through backend/providers/registry.get_llm_provider() -- never
    instantiates a provider directly.
    """

    async def generate_intent_result(
        self,
        context: str,
        partner_name: str,
        partner_relationship: str,
        utterance: str,
        recent_context: str = "",
    ) -> IntentResult: ...

    async def generate_candidates(
        self,
        user_name: str,
        context: str,
        context_node_ids: list[str],
        partner_name: str,
        partner_relationship: str,
        utterance: str,
        intent: str,
        recent_context: str = "",
    ) -> CandidateResult:
        """Returns validated sentences and their grounding node ids."""
        ...


class PartnerServiceProtocol(Protocol):
    @property
    def current(self) -> PartnerIdentification | None: ...
    async def identify(self, transcript: str) -> PartnerIdentification: ...
    def set_override(
        self, partner_id: str | None
    ) -> PartnerIdentification | Awaitable[PartnerIdentification]: ...


class ExtractionServiceProtocol(Protocol):
    async def extract_and_writeback(self, utterance: str, spoken_text: str) -> ExtractionResult: ...


class OnboardingServiceProtocol(Protocol):
    def seed(self, bio: str, name: str) -> AsyncIterator[BloomBatch]: ...


class SpellerServiceProtocol(Protocol):
    """ARCHITECTURE.md section 13: N-ary tree, one character per traversal."""

    async def root_labels(self) -> list[str]: ...
    async def next_labels(self, path: list[int]) -> list[str] | None:
        """None signals a SPEAK leaf was reached; caller reads .spelled_text()."""
        ...

    def spelled_text(self) -> str: ...
    def reset(self) -> None: ...
