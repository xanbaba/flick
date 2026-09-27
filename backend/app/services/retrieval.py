"""Retrieval (ARCHITECTURE.md section 11).

Four stages, under 150 ms total at 150-300 nodes:

1. Seed. Embed the query. Cosine against all node embeddings via
   ``GraphService.vector_search``. Top ``vector_top_k`` (25).
2. Expand. Two-hop traversal from seeds, union with seeds, truncate to
   ``candidate_cap`` (60) preferring higher weight.
3. Partner boost. If a partner is identified, unconditionally add that
   Person node and everything within one hop. This is what makes the
   same intent produce a different sentence depending on who is
   listening.
4. Submodular selection. Facility-location greedy maximisation over
   the candidate embeddings, maximising coverage rather than returning
   near-duplicates.

Stage 4 was originally built on ``apricot.FacilityLocationSelection``
(SW-5), but measured at ~800-900 ms for a 60x384 candidate matrix on
this machine -- five to six times the section 11 latency budget for
*all four stages combined*, confirmed by direct profiling
(``FacilityLocationSelection(n_samples=8, metric="cosine").fit(X)``
repeated 5 times in the same process, never dropping below ~800 ms,
ruling out one-time JIT warm-up). The task brief requires measuring
retrieval latency and reporting the number, not asserting the
specified library meets it, so stage 4 is a direct numpy
implementation of the same greedy submodular facility-location
maximisation apricot performs -- see ``_facility_location_greedy``
below -- which is sub-millisecond at this problem size.
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
from pydantic import BaseModel

from backend.app.services.graph import EdgeRef, GraphService, NodeRef
from backend.app.services.tiger import TigerGraphService
from backend.providers.base import EmbeddingProvider
from backend.providers.registry import get_embedding_provider
from shared.config import RetrievalConfig, get_settings


def _facility_location_greedy(embeddings: np.ndarray, k: int) -> list[int]:
    """Greedy submodular maximisation of the facility-location objective.

    Same algorithm ``apricot.FacilityLocationSelection`` implements:
    repeatedly pick the point that most increases total coverage, where
    coverage of a selected set is, for every point, its similarity to
    the *closest* (most similar) selected point. Returns the selected
    row indices into ``embeddings``, in selection order.

    Cosine similarity is remapped from [-1, 1] to [0, 1] because
    facility-location gains must be non-negative for the greedy
    algorithm's approximation guarantee to hold.
    """
    n = embeddings.shape[0]
    k = min(k, n)
    if k <= 0:
        return []

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-12, norms)
    normalized = embeddings / norms
    similarity = (normalized @ normalized.T + 1.0) / 2.0

    coverage = np.zeros(n)
    selected: list[int] = []
    selected_mask = np.zeros(n, dtype=bool)
    for _ in range(k):
        gains = np.sum(np.maximum(coverage[:, None], similarity) - coverage[:, None], axis=0)
        gains[selected_mask] = -np.inf
        best = int(np.argmax(gains))
        selected.append(best)
        selected_mask[best] = True
        coverage = np.maximum(coverage, similarity[:, best])
    return selected


class RetrievalResult(BaseModel):
    """ARCHITECTURE.md section 11."""

    nodes: list[NodeRef]  # the select_k selected
    edges: list[EdgeRef]
    context_text: str
    activated_node_ids: list[str]  # everything traversed, for graph.activate


class RetrievalService:
    def __init__(
        self,
        graph: GraphService,
        embedder: EmbeddingProvider | None = None,
        config: RetrievalConfig | None = None,
    ) -> None:
        self._graph = graph
        self._embedder = embedder or get_embedding_provider()
        self._config = config or get_settings().config.retrieval

    def retrieve(self, query_text: str, partner_id: str | None = None) -> RetrievalResult:
        """Run all four stages and return the eight (``select_k``) selected facts.

        ``query_text`` is the partner utterance for round one, or the
        utterance plus the chosen intent label for round two (section
        11's stage 1 note) -- the caller is responsible for
        concatenating those; this service only embeds whatever text
        it is given.
        """
        seeds = self._seed(query_text)
        expanded = self._expand(seeds)

        activated_ids: list[str] = [n.id for n in expanded]
        candidates: dict[str, NodeRef] = {n.id: n for n in expanded}

        partner_node: NodeRef | None = None
        if partner_id:
            partner_node = self._partner_boost(partner_id, candidates, activated_ids)

        selected = self._select(list(candidates.values()), must_include=partner_node)
        edges = self._collect_edges(selected)
        context_text = self._render_context(selected)

        return RetrievalResult(
            nodes=selected,
            edges=edges,
            context_text=context_text,
            activated_node_ids=activated_ids,
        )

    # ---------------------------------------------------------------- #
    # Stage 1: seed
    # ---------------------------------------------------------------- #

    def _seed(self, query_text: str) -> list[NodeRef]:
        q_vec = self._embedder.embed([query_text])[0] if query_text else None
        if q_vec is None:
            return []
        return self._graph.vector_search(np.asarray(q_vec), k=self._config.vector_top_k)

    # ---------------------------------------------------------------- #
    # Stage 2: expand
    # ---------------------------------------------------------------- #

    def _expand(self, seeds: list[NodeRef]) -> list[NodeRef]:
        if not seeds:
            return []
        return self._graph.expand(seeds, hops=self._config.hops, cap=self._config.candidate_cap)

    # ---------------------------------------------------------------- #
    # Stage 3: partner boost
    # ---------------------------------------------------------------- #

    def _partner_boost(
        self, partner_id: str, candidates: dict[str, NodeRef], activated_ids: list[str]
    ) -> NodeRef | None:
        partner_node = self._graph.get_node(partner_id)
        if partner_node is None:
            return None
        # Large cap: "everything within one hop" is unconditional, not
        # subject to candidate_cap truncation (section 11 stage 3).
        boosted = self._graph.expand([partner_node], hops=1, cap=10_000)
        for node in boosted:
            candidates[node.id] = node
            if node.id not in activated_ids:
                activated_ids.append(node.id)
        return partner_node

    # ---------------------------------------------------------------- #
    # Stage 4: submodular selection
    # ---------------------------------------------------------------- #

    def _select(
        self, candidates: list[NodeRef], must_include: NodeRef | None = None
    ) -> list[NodeRef]:
        """Stage 4. ``must_include`` (the boosted partner node, if any) is

        forced into the result even if facility location would not
        otherwise have picked it -- the partner boost only earns its
        keep (section 11's "most persuasive behaviour in the demo") if
        the listener's own node reliably survives to the rendered
        context, not just to the candidate pool.
        """
        k = self._config.select_k
        if not candidates:
            return []
        if len(candidates) <= k:
            ordered = sorted(candidates, key=lambda n: n.weight, reverse=True)
        else:
            matrix = self._embedding_matrix(candidates)
            ranking = _facility_location_greedy(matrix, k)
            ordered = [candidates[i] for i in ranking]

        if must_include is not None and all(n.id != must_include.id for n in ordered):
            ordered = [*ordered[: max(0, k - 1)], must_include]
        return ordered[:k]

    def _embedding_matrix(self, candidates: list[NodeRef]) -> np.ndarray:
        missing_ids = [c.id for c in candidates if c.embedding is None]
        fetched = self._graph.get_embeddings(missing_ids) if missing_ids else {}
        dim = self._graph.embedding_dim
        rows = []
        for c in candidates:
            if c.embedding is not None:
                rows.append(np.asarray(c.embedding, dtype=np.float64))
            else:
                rows.append(fetched.get(c.id, np.zeros(dim, dtype=np.float64)))
        return np.vstack(rows)

    # ---------------------------------------------------------------- #
    # Rendering
    # ---------------------------------------------------------------- #

    def _collect_edges(self, nodes: list[NodeRef]) -> list[EdgeRef]:
        return self._graph.edges_among([n.id for n in nodes])

    @staticmethod
    def _render_context(nodes: list[NodeRef]) -> str:
        """Section 11: "Context is rendered one fact per line."""
        lines = [f"- {' '.join(n.fact.split())}" for n in nodes if n.fact]
        return "\n".join(lines)


def time_retrieval(
    service: RetrievalService, query_text: str, partner_id: str | None = None
) -> tuple[RetrievalResult, float]:
    """Helper for measuring the section 11 latency budget (<150 ms).

    Returns ``(result, elapsed_ms)``. Not part of the frozen
    ``RetrievalResult`` shape -- this is purely a benchmarking hook
    used by tests/test_retrieval.py and the demo script.
    """
    t0 = time.perf_counter()
    result = service.retrieve(query_text, partner_id=partner_id)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return result, elapsed_ms


class TigerRetrievalService(RetrievalService):
    """Same domain result and NumPy selection, with genuinely async database I/O."""

    def __init__(self, graph: TigerGraphService, config: RetrievalConfig) -> None:
        self._graph = graph
        self._config = config

    async def retrieve(self, query_text: str, partner_id: str | None = None) -> RetrievalResult:
        if not query_text.strip():
            return RetrievalResult(nodes=[], edges=[], context_text="", activated_node_ids=[])
        query = (await self._graph.embed([query_text]))[0]
        seeds = await self._graph.vector_search(query, self._config.vector_top_k)
        expanded = await self._graph.expand(seeds, self._config.hops, self._config.candidate_cap)
        candidates = {n.id: n for n in expanded}
        partner_node = await self._graph.get_node(partner_id) if partner_id else None
        if partner_node is not None:
            boosted = await self._graph.expand([partner_node], 1, self._config.candidate_cap)
            candidates.update({n.id: n for n in boosted})
        # Stable ordering makes equal facility-location gains deterministic.
        bounded = sorted(candidates.values(), key=lambda n: (-n.weight, n.id))[
            : self._config.candidate_cap
        ]
        if partner_node is not None and partner_node.id not in {n.id for n in bounded}:
            bounded = bounded[:-1] + [partner_node]
        bounded.sort(key=lambda n: n.id)
        selected = await asyncio.to_thread(self._select, bounded, partner_node)
        edges = await self._graph.edges_among([n.id for n in selected])
        return RetrievalResult(
            nodes=selected,
            edges=edges,
            context_text=self._render_context(selected),
            activated_node_ids=[n.id for n in bounded],
        )
