"""Tests for backend.app.services.extraction (ARCHITECTURE.md section 12.4)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from backend.app.services.extraction import ExtractionService
from backend.app.services.graph import GraphService
from backend.providers.base import LLMProvider
from backend.providers.llm_static import StaticLLMProvider
from shared.config import ExtractionConfig


class _ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    async def complete(
        self, system: str, user: str, *, json_mode: bool = False, max_tokens=400, timeout=6.0
    ) -> str:
        del system, user, json_mode, max_tokens, timeout
        return self._responses.pop(0)


@pytest.fixture
def config() -> ExtractionConfig:
    return ExtractionConfig(
        enabled=True, confidence_threshold=0.7, max_new_nodes_per_turn=4, dedup_similarity=0.88
    )


@pytest.fixture
def graph(tmp_path: Path) -> GraphService:
    g = GraphService(db_path=tmp_path / "kuzu", embedding_dim=384)
    g.upsert_node("Person", {"id": "user", "name": "Marcus", "relationship": "self"})
    return g


def test_disabled_extraction_is_a_no_op(graph: GraphService, config: ExtractionConfig) -> None:
    config.enabled = False
    svc = ExtractionService(graph, llm=StaticLLMProvider(), config=config)
    result = asyncio.run(svc.extract_and_writeback("How's the chair?", "It's fine."))
    assert result.committed_node_ids == []
    assert graph.node_count() == 1  # only "user"


def test_static_fallback_never_raises_and_commits_nothing(
    graph: GraphService, config: ExtractionConfig
) -> None:
    svc = ExtractionService(graph, llm=StaticLLMProvider(), config=config)
    result = asyncio.run(svc.extract_and_writeback("Do you need anything?", "A new chair."))
    assert result.committed_node_ids == []
    assert result.committed_edge_ids == []


def test_extraction_commits_a_confident_node_and_edge(
    graph: GraphService, config: ExtractionConfig
) -> None:
    payload = json.dumps(
        {
            "nodes": [
                {
                    "kind": "Thing",
                    "name": "adjustable chair",
                    "notes": "You need an adjustable chair.",
                    "confidence": 0.9,
                }
            ],
            "edges": [
                {
                    "kind": "NEEDS",
                    "source": "user",
                    "target_name": "adjustable chair",
                    "confidence": 0.85,
                }
            ],
        }
    )
    svc = ExtractionService(graph, llm=_ScriptedLLM([payload]), config=config)
    result = asyncio.run(svc.extract_and_writeback("Do you need anything?", "An adjustable chair."))
    assert len(result.committed_node_ids) == 1
    assert len(result.committed_edge_ids) == 1
    assert graph.node_count() == 2  # user + the new Thing


def test_low_confidence_nodes_are_discarded(graph: GraphService, config: ExtractionConfig) -> None:
    payload = json.dumps(
        {
            "nodes": [
                {"kind": "Thing", "name": "maybe a hat", "notes": "...", "confidence": 0.3},
            ],
            "edges": [],
        }
    )
    svc = ExtractionService(graph, llm=_ScriptedLLM([payload]), config=config)
    result = asyncio.run(svc.extract_and_writeback("u", "s"))
    assert result.committed_node_ids == []
    assert graph.node_count() == 1


def test_max_new_nodes_per_turn_is_respected(graph: GraphService, config: ExtractionConfig) -> None:
    config.max_new_nodes_per_turn = 2
    payload = json.dumps(
        {
            "nodes": [
                {"kind": "Thing", "name": f"thing {i}", "notes": "n", "confidence": 0.9}
                for i in range(5)
            ],
            "edges": [],
        }
    )
    svc = ExtractionService(graph, llm=_ScriptedLLM([payload]), config=config)
    result = asyncio.run(svc.extract_and_writeback("u", "s"))
    assert len(result.committed_node_ids) == 2


def test_dedup_reinforces_instead_of_duplicating(
    graph: GraphService, config: ExtractionConfig
) -> None:
    graph.upsert_node(
        "Thing", {"id": "rosie", "name": "Rosie the beagle", "notes": "Rosie is your dog."}
    )
    before_count = graph.node_count()

    payload = json.dumps(
        {
            "nodes": [
                {
                    "kind": "Thing",
                    "name": "Rosie the beagle",
                    "notes": "Rosie is your dog.",
                    "confidence": 0.95,
                }
            ],
            "edges": [],
        }
    )
    svc = ExtractionService(graph, llm=_ScriptedLLM([payload]), config=config)
    result = asyncio.run(svc.extract_and_writeback("u", "s"))

    assert result.committed_node_ids == []
    assert result.reinforced_node_ids == ["rosie"]
    assert graph.node_count() == before_count  # no duplicate created


def test_repair_retry_on_malformed_json(graph: GraphService, config: ExtractionConfig) -> None:
    good = json.dumps({"nodes": [], "edges": []})
    svc = ExtractionService(graph, llm=_ScriptedLLM(["garbage", good]), config=config)
    result = asyncio.run(svc.extract_and_writeback("u", "s"))
    assert result.committed_node_ids == []
