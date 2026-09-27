"""Tests for onboarding, the Marcus fixture, and a grounded offline turn."""

from __future__ import annotations

import asyncio
from pathlib import Path

from backend.app.services.generation import GenerationService
from backend.app.services.graph import GraphService
from backend.app.services.onboarding import BLOOM_BATCH, OnboardingService, load_fixture
from backend.app.services.persona import DEMO_BIO, DEMO_NAME
from backend.app.services.retrieval import RetrievalService, time_retrieval
from backend.providers.llm_static import StaticLLMProvider


def test_fixture_has_between_150_and_300_nodes() -> None:
    payload = load_fixture()
    assert 150 <= len(payload["nodes"]) <= 300
    kinds = {node["kind"] for node in payload["nodes"]}
    assert kinds == {"Person", "Place", "Thing", "Activity", "Need", "Memory"}
    ids = {node["id"] for node in payload["nodes"]}
    assert "user" in ids
    assert "sofia" in ids
    assert "rosie" in ids


def test_static_onboarding_seeds_fixture_and_blooms_in_batches(tmp_path: Path) -> None:
    graph = GraphService(db_path=tmp_path / "kuzu", embedding_dim=384)
    service = OnboardingService(graph, llm=StaticLLMProvider(), interval_s=0)

    async def collect() -> list:
        return [batch async for batch in service.seed(DEMO_BIO, DEMO_NAME)]

    batches = asyncio.run(collect())
    assert graph.node_count() == len(load_fixture()["nodes"])
    assert all(len(batch.nodes) <= BLOOM_BATCH for batch in batches)
    assert len(batches[0].nodes) == BLOOM_BATCH
    assert sum(len(batch.nodes) for batch in batches) == graph.node_count()


def test_seeded_turn_yields_three_grounded_sentences(tmp_path: Path) -> None:
    graph = GraphService(db_path=tmp_path / "kuzu", embedding_dim=384)
    graph.seed_from_json(load_fixture())
    retrieval = RetrievalService(graph)
    result, elapsed_ms = time_retrieval(
        retrieval,
        "Did you walk Rosie, and how's your back in that recliner?",
        partner_id="sofia",
    )
    assert elapsed_ms < 150.0
    generation = GenerationService(llm=StaticLLMProvider())
    candidates = asyncio.run(
        generation.generate_candidates(
            user_name="Marcus",
            context=result.context_text,
            context_node_ids=[node.id for node in result.nodes],
            partner_name="Sofia",
            partner_relationship="daughter",
            utterance="Did you walk Rosie, and how's your back in that recliner?",
            intent="Talk about Rosie",
        )
    )
    known = {node.id for node in graph.snapshot()[0]}
    assert len(candidates.candidates) == 3
    assert candidates.grounding
    assert set(candidates.grounding) <= known
