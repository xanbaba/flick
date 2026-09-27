"""Persistent service contracts, without network or model downloads."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.app.services.extraction import ExtractedEdge, ExtractedNode, ExtractionService
from backend.app.services.graph import GraphService
from backend.app.services.onboarding import OnboardingService, SeedUnavailableError
from backend.app.services.partner import PartnerService
from backend.app.services.persona import DEMO_BIO, DEMO_NAME
from backend.app.services.retrieval import RetrievalService
from backend.app.services.worker import MemoryWorker
from backend.providers.base import LLMProvider


@pytest.fixture
def graph(tmp_path: Path) -> Iterator[GraphService]:
    graph = GraphService(tmp_path / "graph")
    yield graph
    graph.close()


def test_seed_storage_failure_rolls_back(
    graph: GraphService, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = graph.upsert_node

    def fail(kind: str, props: dict) -> str:
        if props["id"] == "pet":
            raise RuntimeError("storage failure")
        return original(kind, props)

    monkeypatch.setattr(graph, "upsert_node", fail)
    with pytest.raises(RuntimeError, match="storage failure"):
        graph.seed_from_json(
            {
                "nodes": [
                    {"id": "user", "kind": "Person", "name": "Alex"},
                    {"id": "pet", "kind": "Thing", "name": "Milo"},
                ]
            }
        )
    assert graph.node_count() == 0
    assert graph.snapshot() == ([], [])


@pytest.mark.parametrize("name,bio", [("Alex", "Alex likes tea"), (DEMO_NAME, "edited bio")])
async def test_custom_biography_never_becomes_marcus(
    graph: GraphService, name: str, bio: str
) -> None:
    service = OnboardingService(graph)
    with pytest.raises(SeedUnavailableError, match="try again"):
        _ = [batch async for batch in service.seed(bio, name)]
    assert graph.node_count() == 0


async def test_demo_fallback_ignores_whitespace(graph: GraphService) -> None:
    service = OnboardingService(graph, interval_s=0)
    batches = [batch async for batch in service.seed(" \n".join(DEMO_BIO.split()), DEMO_NAME)]
    assert sum(len(batch.nodes) for batch in batches) >= 150


async def test_valid_first_pass_survives_expansion_failure(graph: GraphService) -> None:
    llm = AsyncMock(spec=LLMProvider)
    llm.complete.side_effect = [
        json.dumps(
            {
                "nodes": [{"id": "tea", "kind": "Thing", "name": "tea", "notes": "You like tea."}],
                "edges": [{"kind": "LIKES", "source": "user", "target": "tea"}],
            }
        ),
        TimeoutError(),
    ]
    service = OnboardingService(graph, llm=llm, interval_s=0)
    _ = [batch async for batch in service.seed("Alex likes tea", "Alex")]
    assert next(p for p in graph.people() if p.id == "user").name == "Alex"
    assert len(graph.snapshot()[1]) == 1


async def test_extracted_memory_preserves_text(graph: GraphService) -> None:
    graph.upsert_node("Person", {"id": "user", "name": "Alex"})
    llm = AsyncMock(spec=LLMProvider)
    llm.complete.return_value = json.dumps(
        {
            "nodes": [
                {
                    "kind": "Memory",
                    "name": "Sunday visit",
                    "notes": "You visited the lake on Sunday.",
                    "confidence": 0.95,
                }
            ],
            "edges": [],
        }
    )
    result = await ExtractionService(graph, llm=llm).extract_and_writeback("lake?", "Sunday")
    node = graph.get_node(result.committed_node_ids[0])
    assert node.fact == "You visited the lake on Sunday."
    again = await ExtractionService(graph, llm=llm).extract_and_writeback("lake?", "Sunday")
    assert again.committed_node_ids == []
    assert again.reinforced_node_ids == [node.id]


async def test_partner_failure_keeps_previous_and_override_requires_person(
    graph: GraphService,
) -> None:
    graph.upsert_node("Person", {"id": "sam", "name": "Sam"})
    llm = AsyncMock(spec=LLMProvider)
    llm.complete.side_effect = [
        '{"partner_id":"sam","confidence":0.9,"reason":"introduced himself"}',
        TimeoutError(),
    ]
    service = PartnerService(graph, llm=llm)
    assert (await service.identify("Sam here")).partner_id == "sam"
    assert (await service.identify("hello")).partner_id == "sam"
    with pytest.raises(ValueError, match="known person"):
        service.set_override("missing")


async def test_worker_serializes_database_lifecycle(tmp_path: Path) -> None:
    worker = MemoryWorker()
    graph = await worker.run(GraphService, tmp_path / "graph")
    try:
        await worker.run(graph.upsert_node, "Person", {"id": "user", "name": "Alex"})
        assert await worker.run(graph.node_count) == 1
    finally:
        await worker.run(graph.close)
        await worker.close()
    reopened = GraphService(tmp_path / "graph")
    assert reopened.people()[0].name == "Alex"
    reopened.close()


def test_demo_biography_matches_dashboard_prefill() -> None:
    source = Path("frontend/src/lib/persona.ts").read_text(encoding="utf-8")
    assert DEMO_BIO in source


def test_malformed_seed_proposals_are_dropped(graph: GraphService) -> None:
    result = graph.seed_from_json(
        {
            "nodes": [
                {"kind": [], "name": "invalid"},
                {"id": [], "kind": "Thing", "name": "tea"},
                {"id": "user", "kind": "Person", "name": "Alex"},
            ],
            "edges": [{"kind": [], "source": "user", "target": "user"}],
        }
    )
    assert result.node_count == 1
    assert result.dropped == 3


async def test_override_wins_during_inflight_identification(graph: GraphService) -> None:
    graph.upsert_node("Person", {"id": "sam", "name": "Sam"})
    graph.upsert_node("Person", {"id": "pat", "name": "Pat"})
    entered, release = asyncio.Event(), asyncio.Event()

    async def identify(*args: object, **kwargs: object) -> str:
        entered.set()
        await release.wait()
        return '{"partner_id":"sam","confidence":0.95,"reason":"name"}'

    llm = AsyncMock(spec=LLMProvider)
    llm.complete.side_effect = identify
    service = PartnerService(graph, llm=llm)
    task = asyncio.create_task(service.identify("Sam here"))
    await entered.wait()
    service.set_override("pat")
    release.set()
    assert (await task).partner_id == "pat"


def test_writeback_storage_failure_rolls_back_new_nodes(
    graph: GraphService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph.upsert_node("Person", {"id": "user", "name": "Alex"})

    def fail(*args: object, **kwargs: object) -> str:
        raise RuntimeError("storage failure")

    monkeypatch.setattr(graph, "upsert_edge", fail)
    with pytest.raises(RuntimeError, match="storage failure"):
        ExtractionService(graph)._commit_atomic(
            [ExtractedNode(kind="Thing", name="mint tea", notes="You have tea.", confidence=0.9)],
            [ExtractedEdge(kind="LIKES", source="user", target_name="mint tea", confidence=0.9)],
        )
    assert graph.node_count() == 1


def test_retrieval_preserves_one_fact_per_node(graph: GraphService) -> None:
    graph.upsert_node(
        "Thing", {"id": "tea", "name": "mint tea", "notes": "You have mint tea.\n- It is warm."}
    )
    graph.upsert_node("Person", {"id": "user", "name": "Alex"})
    result = RetrievalService(graph).retrieve("mint tea")
    assert len(result.context_text.splitlines()) == len(result.nodes)
    assert "You have mint tea. - It is warm." in result.context_text
