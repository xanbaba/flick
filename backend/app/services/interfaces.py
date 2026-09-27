"""Protocols for the knowledge-layer services owned by another agent.

graph.py, retrieval.py, generation.py, extraction.py, partner.py,
onboarding.py and speller.py (ARCHITECTURE.md sections 10-14) are out
of scope for backend/app/ -- AGENTS.md's ownership table assigns them
to Dev D. orchestrator.py, ws.py and main.py must still call
something shaped like them, so these Protocols are that "something":
a thin, structural contract copied straight from the ARCHITECTURE.md
signatures, with no implementation.

The orchestrator accepts every one of these as an optional
constructor argument. When a real implementation is not injected
(``None``), the orchestrator falls back to the minimal built-in
behaviour documented on each of its own methods -- enough to drive a
complete turn end to end for acceptance test A6, not a substitute for
the real thing. Whoever implements graph.py etc. can be dropped in
without changing orchestrator.py, ws.py or main.py: only the
construction site (main.py's DI container) needs to change.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
from pydantic import BaseModel

from backend.app.services.generation import CandidateResult
from shared.schemas import GraphEdge, GraphNode

# --------------------------------------------------------------------------
# Supporting types (ARCHITECTURE.md sections 10-12). Not part of
# shared/schemas.py's frozen wire contract -- these never cross a
# process boundary as their own message type.
# --------------------------------------------------------------------------


class NodeRef(BaseModel):
    id: str
    kind: str
    weight: float = 1.0


class EdgeRef(BaseModel):
    id: str
    kind: str
    source: str
    target: str


class SeedResult(BaseModel):
    node_count: int
    edge_count: int


class Person(BaseModel):
    id: str
    name: str
    relationship: str


class RetrievalResult(BaseModel):
    """ARCHITECTURE.md section 11."""

    nodes: list[NodeRef]  # the select_k selected
    edges: list[EdgeRef]
    context_text: str
    activated_node_ids: list[str]  # everything traversed, for graph.activate


class PartnerIdResult(BaseModel):
    """ARCHITECTURE.md section 12.3."""

    partner_id: str | None
    confidence: float
    reason: str


class ExtractionResult(BaseModel):
    """ARCHITECTURE.md section 12.4 -- the graph.bloom payload."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]


# --------------------------------------------------------------------------
# Service Protocols.
# --------------------------------------------------------------------------


class GraphServiceProtocol(Protocol):
    """ARCHITECTURE.md section 10.2."""

    def ensure_schema(self) -> None: ...
    def seed_from_json(self, payload: dict) -> SeedResult: ...
    def snapshot(self) -> tuple[list[GraphNode], list[GraphEdge]]: ...
    def vector_search(self, q: np.ndarray, k: int) -> list[NodeRef]: ...
    def expand(self, seeds: list[NodeRef], hops: int, cap: int) -> list[NodeRef]: ...
    def reinforce(self, node_ids: list[str], edge_ids: list[str]) -> None: ...
    def upsert_node(self, kind: str, props: dict) -> str: ...
    def upsert_edge(self, kind: str, src: str, dst: str, props: dict) -> str: ...
    def people(self) -> list[Person]: ...
    def node_count(self) -> int: ...


class RetrievalServiceProtocol(Protocol):
    """ARCHITECTURE.md section 11: seed, expand, partner boost, submodular select."""

    async def retrieve(
        self, query: str, *, partner_id: str | None, select_k: int
    ) -> RetrievalResult: ...


class GenerationServiceProtocol(Protocol):
    """ARCHITECTURE.md section 12.1-12.2. Calls LLMProvider.complete()

    through backend/providers/registry.get_llm_provider() -- never
    instantiates a provider directly.
    """

    async def generate_intents(
        self, context: str, partner_name: str, partner_relationship: str, utterance: str
    ) -> list[str]: ...

    async def generate_candidates(
        self,
        user_name: str,
        context: str,
        context_node_ids: list[str],
        partner_name: str,
        partner_relationship: str,
        utterance: str,
        intent: str,
    ) -> CandidateResult:
        """Returns validated sentences and their grounding node ids."""
        ...


class PartnerServiceProtocol(Protocol):
    """ARCHITECTURE.md section 12.3."""

    async def identify(self, transcript: str) -> PartnerIdResult: ...
    def set_override(self, partner_id: str) -> None: ...
    def get_current(self) -> Person | None: ...


class ExtractionServiceProtocol(Protocol):
    """ARCHITECTURE.md section 12.4."""

    async def extract_and_writeback(self, utterance: str, spoken_text: str) -> ExtractionResult: ...


class OnboardingServiceProtocol(Protocol):
    """ARCHITECTURE.md section 14."""

    async def seed(self, bio: str, name: str) -> SeedResult: ...
    def status(self) -> dict:
        """{"seeded": bool, "node_count": int}"""
        ...


class SpellerServiceProtocol(Protocol):
    """ARCHITECTURE.md section 13: N-ary tree, one character per traversal."""

    async def root_labels(self) -> list[str]: ...
    async def next_labels(self, path: list[int]) -> list[str] | None:
        """None signals a SPEAK leaf was reached; caller reads .spelled_text()."""
        ...

    def spelled_text(self) -> str: ...
    def reset(self) -> None: ...
