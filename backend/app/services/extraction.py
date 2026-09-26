"""Fact extraction and writeback (ARCHITECTURE.md section 12.4).

Runs after each spoken turn with the utterance, the spoken sentence
and a graph summary. Proposals below ``confidence_threshold`` are
discarded; at most ``max_new_nodes_per_turn`` commit. Each surviving
node proposal is checked against existing nodes by cosine similarity
-- above ``dedup_similarity`` (0.88) it reinforces the existing node
instead of creating a duplicate. "Without this check the graph fills
with near-identical nodes within five turns."
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from backend.app.services.graph import NODE_COLUMN_TYPES, REL_PAIRS, GraphService
from backend.providers.base import EmbeddingProvider, LLMProvider
from backend.providers.registry import get_embedding_provider, get_llm_provider
from shared.config import ExtractionConfig, get_settings

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

_GENERIC_SYSTEM_PROMPT = (
    "You are the fact-extraction stage of Flick, a speech device for someone "
    "who cannot speak. Follow the instructions in the user message exactly. "
    "Respond with nothing but the JSON object it asks for -- no prose, no "
    "markdown fences, no commentary before or after."
)


class ExtractedNode(BaseModel):
    kind: str
    name: str
    notes: str
    confidence: float


class ExtractedEdge(BaseModel):
    kind: str
    source: str
    target_name: str
    confidence: float


class ExtractionResult(BaseModel):
    """Not part of shared/schemas.py -- graph.bloom (out of scope here,

    orchestrator's job) is built from committed_node_ids/committed_edge_ids.
    """

    committed_node_ids: list[str]
    committed_edge_ids: list[str]
    reinforced_node_ids: list[str]  # deduped against an existing node instead


def _fill(template: str, **values: str) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def _extract_json_object(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        newline = text.find("\n")
        if newline != -1 and not text[:newline].strip().startswith("{"):
            text = text[newline + 1 :]
    return text.strip()


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(a @ b / denom)


class ExtractionService:
    """ARCHITECTURE.md section 12.4."""

    def __init__(
        self,
        graph: GraphService,
        llm: LLMProvider | None = None,
        embedder: EmbeddingProvider | None = None,
        config: ExtractionConfig | None = None,
        prompts_dir: Path = PROMPTS_DIR,
    ) -> None:
        self._graph = graph
        self._llm = llm or get_llm_provider()
        self._embedder = embedder or get_embedding_provider()
        self._config = config or get_settings().config.extraction
        self._template = (prompts_dir / "extraction.txt").read_text(encoding="utf-8")

    async def extract_and_writeback(self, utterance: str, spoken_text: str) -> ExtractionResult:
        empty = ExtractionResult(
            committed_node_ids=[], committed_edge_ids=[], reinforced_node_ids=[]
        )
        if not self._config.enabled:
            return empty

        prompt = _fill(
            self._template,
            graph_summary=self._summarize_graph(),
            utterance=utterance,
            spoken_text=spoken_text,
        )
        raw = await self._complete(prompt)
        parsed = self._parse(raw)
        if parsed is None:
            raw_retry = await self._complete(self._repair_prompt(prompt, raw))
            parsed = self._parse(raw_retry)
        if parsed is None:
            return empty

        nodes, edges = parsed
        return self._commit(nodes, edges)

    # ---------------------------------------------------------------- #
    # Writeback
    # ---------------------------------------------------------------- #

    def _commit(self, nodes: list[ExtractedNode], edges: list[ExtractedEdge]) -> ExtractionResult:
        confident_nodes = [n for n in nodes if n.confidence >= self._config.confidence_threshold]
        confident_nodes = confident_nodes[: self._config.max_new_nodes_per_turn]

        committed_node_ids: list[str] = []
        reinforced_node_ids: list[str] = []
        name_to_id: dict[str, str] = {}

        for node in confident_nodes:
            if node.kind not in NODE_COLUMN_TYPES:
                continue
            existing_id = self._find_duplicate(node.kind, node.name)
            if existing_id is not None:
                self._graph.reinforce(node_ids=[existing_id], edge_ids=[])
                reinforced_node_ids.append(existing_id)
                name_to_id[node.name] = existing_id
            else:
                node_id = self._graph.upsert_node(
                    node.kind, {"name": node.name, "notes": node.notes}
                )
                committed_node_ids.append(node_id)
                name_to_id[node.name] = node_id

        committed_edge_ids: list[str] = []
        for edge in edges:
            if edge.confidence < self._config.confidence_threshold:
                continue
            if edge.kind not in REL_PAIRS:
                continue
            target_id = name_to_id.get(edge.target_name) or self._resolve_existing_by_name(
                edge.target_name
            )
            if target_id is None:
                continue
            try:
                edge_id = self._graph.upsert_edge(edge.kind, edge.source, target_id, {})
            except ValueError:
                continue
            committed_edge_ids.append(edge_id)

        return ExtractionResult(
            committed_node_ids=committed_node_ids,
            committed_edge_ids=committed_edge_ids,
            reinforced_node_ids=reinforced_node_ids,
        )

    def _find_duplicate(self, kind: str, name: str) -> str | None:
        """Cosine dedup check (section 12.4's own words: "without this

        check the graph fills with near-identical nodes within five
        turns"). Only matches within the same node kind.
        """
        query_embedding = self._embedder.embed([name])[0]
        candidates = self._graph.vector_search(query_embedding, k=5)
        best_id: str | None = None
        best_similarity = 0.0
        for candidate in candidates:
            if candidate.kind != kind or candidate.embedding is None:
                continue
            similarity = _cosine(query_embedding, np.asarray(candidate.embedding))
            if similarity > best_similarity:
                best_similarity = similarity
                best_id = candidate.id
        if best_id is not None and best_similarity >= self._config.dedup_similarity:
            return best_id
        return None

    def _resolve_existing_by_name(self, name: str) -> str | None:
        """An edge's target_name may reference a node already in the

        graph rather than one just proposed this turn -- best-effort
        match by the same cosine test, any kind.
        """
        query_embedding = self._embedder.embed([name])[0]
        candidates = self._graph.vector_search(query_embedding, k=1)
        if not candidates:
            return None
        best = candidates[0]
        if best.embedding is None:
            return None
        similarity = _cosine(query_embedding, np.asarray(best.embedding))
        return best.id if similarity >= self._config.dedup_similarity else None

    def _summarize_graph(self) -> str:
        nodes, _ = self._graph.snapshot()
        if not nodes:
            return "(empty -- nothing recorded yet)"
        lines = [f"- {n.id} ({n.kind}): {n.label}" for n in nodes]
        return "\n".join(lines)

    # ---------------------------------------------------------------- #
    # LLM plumbing (section 12: strict JSON, one repair retry)
    # ---------------------------------------------------------------- #

    async def _complete(self, user_prompt: str) -> str:
        return await self._llm.complete(
            _GENERIC_SYSTEM_PROMPT,
            user_prompt,
            json_mode=True,
            max_tokens=400,
            timeout=6.0,
        )

    @staticmethod
    def _repair_prompt(original_prompt: str, bad_response: str) -> str:
        return (
            "Your previous response was not valid JSON in the exact shape "
            "requested. Here is what you returned:\n\n"
            f"{bad_response}\n\n"
            "Re-read the instructions below and respond again with ONLY the "
            "JSON object, nothing else.\n\n"
            f"{original_prompt}"
        )

    def _parse(self, raw: str) -> tuple[list[ExtractedNode], list[ExtractedEdge]] | None:
        try:
            data = json.loads(_extract_json_object(raw))
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        raw_nodes = data.get("nodes", [])
        raw_edges = data.get("edges", [])
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            return None
        try:
            nodes = [ExtractedNode.model_validate(n) for n in raw_nodes]
            edges = [ExtractedEdge.model_validate(e) for e in raw_edges]
        except Exception:
            return None
        return nodes, edges
