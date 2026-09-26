"""Tests for backend.app.services.retrieval (ARCHITECTURE.md section 11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.services.graph import GraphService
from backend.app.services.retrieval import RetrievalService, time_retrieval
from shared.config import RetrievalConfig


@pytest.fixture
def small_config() -> RetrievalConfig:
    return RetrievalConfig(vector_top_k=5, hops=2, candidate_cap=20, select_k=4)


@pytest.fixture
def seeded_graph(tmp_path: Path) -> GraphService:
    graph = GraphService(db_path=tmp_path / "kuzu", embedding_dim=384)
    graph.upsert_node(
        "Person",
        {
            "id": "user",
            "name": "Marcus",
            "relationship": "self",
            "notes": "Marcus is the user of this device.",
        },
    )
    graph.upsert_node(
        "Person",
        {
            "id": "sofia",
            "name": "Sofia",
            "relationship": "daughter",
            "address_terms": ["mija"],
            "notes": 'Sofia is your daughter. You call her "mija".',
        },
    )
    graph.upsert_node(
        "Activity",
        {
            "id": "sunday_visit",
            "name": "Sunday visit",
            "time_of_day": "afternoon",
            "notes": "Sofia visits on Sunday afternoons.",
        },
    )
    graph.upsert_node(
        "Person",
        {
            "id": "priya",
            "name": "Priya",
            "relationship": "home nurse",
            "notes": "Priya is your home nurse. She comes on weekday mornings.",
        },
    )
    graph.upsert_node(
        "Thing",
        {
            "id": "recliner",
            "name": "the recliner",
            "category": "furniture",
            "notes": "You dislike the recliner; it hurts your back.",
        },
    )
    graph.upsert_node(
        "Thing",
        {
            "id": "rosie",
            "name": "Rosie",
            "category": "pet",
            "notes": "Rosie is your dog, a nine-year-old beagle.",
        },
    )
    graph.upsert_node(
        "Thing",
        {
            "id": "coffee",
            "name": "strong coffee",
            "category": "food",
            "notes": "You like your coffee unreasonably strong.",
        },
    )
    graph.upsert_edge("KNOWS", "user", "sofia", {"weight": 1.0})
    graph.upsert_edge("KNOWS", "user", "priya", {"weight": 1.0})
    graph.upsert_edge("DOES", "user", "sunday_visit", {"weight": 1.0})
    graph.upsert_edge("DISLIKES", "user", "recliner", {"weight": 1.0, "strength": 0.9})
    graph.upsert_edge("LIKES", "user", "rosie", {"weight": 1.0, "strength": 0.9})
    graph.upsert_edge("LIKES", "sofia", "rosie", {"weight": 1.0, "strength": 0.7})
    graph.upsert_edge("LIKES", "user", "coffee", {"weight": 1.0, "strength": 0.8})
    return graph


def test_retrieve_returns_grounded_nodes_with_rendered_context(
    seeded_graph: GraphService, small_config: RetrievalConfig
) -> None:
    service = RetrievalService(seeded_graph, config=small_config)
    result = service.retrieve("Did you walk the dog today?")

    assert 1 <= len(result.nodes) <= small_config.select_k
    node_ids = {n.id for n in result.nodes}
    assert node_ids <= {n.id for n in seeded_graph.snapshot()[0]}
    assert result.context_text  # non-empty, one "- fact" per line
    for line in result.context_text.splitlines():
        assert line.startswith("- ")
    assert len(result.activated_node_ids) >= len(result.nodes)


def test_partner_boost_changes_the_selected_facts(
    seeded_graph: GraphService, small_config: RetrievalConfig
) -> None:
    service = RetrievalService(seeded_graph, config=small_config)

    result_sofia = service.retrieve("How are you?", partner_id="sofia")
    result_priya = service.retrieve("How are you?", partner_id="priya")

    sofia_ids = {n.id for n in result_sofia.nodes}
    priya_ids = {n.id for n in result_priya.nodes}
    assert "sofia" in sofia_ids
    assert "priya" in priya_ids
    # the two listeners pull in different one-hop neighbourhoods
    assert sofia_ids != priya_ids


def test_partner_boost_is_unconditional_even_if_partner_not_seeded_by_query(
    seeded_graph: GraphService, small_config: RetrievalConfig
) -> None:
    service = RetrievalService(seeded_graph, config=small_config)
    result = service.retrieve("completely unrelated gibberish zzz", partner_id="sofia")
    assert "sofia" in result.activated_node_ids


def test_select_k_is_never_exceeded(
    seeded_graph: GraphService, small_config: RetrievalConfig
) -> None:
    service = RetrievalService(seeded_graph, config=small_config)
    result = service.retrieve("tell me about your day")
    assert len(result.nodes) <= small_config.select_k


def test_activated_ids_are_a_superset_of_selected_nodes(
    seeded_graph: GraphService, small_config: RetrievalConfig
) -> None:
    service = RetrievalService(seeded_graph, config=small_config)
    result = service.retrieve("what do you need")
    selected_ids = {n.id for n in result.nodes}
    assert selected_ids <= set(result.activated_node_ids)


def test_empty_graph_returns_empty_result(tmp_path: Path, small_config: RetrievalConfig) -> None:
    graph = GraphService(db_path=tmp_path / "kuzu", embedding_dim=384)
    service = RetrievalService(graph, config=small_config)
    result = service.retrieve("anything")
    assert result.nodes == []
    assert result.context_text == ""
    assert result.activated_node_ids == []


# --------------------------------------------------------------------------
# Latency: section 11 requires all four stages complete under 150 ms at
# 150-300 nodes.
# --------------------------------------------------------------------------


def _build_large_graph(tmp_path: Path, n_nodes: int = 300) -> GraphService:
    graph = GraphService(db_path=tmp_path / "kuzu", embedding_dim=384)
    kinds = ["Thing", "Activity", "Place", "Need"]
    topics = [
        "coffee",
        "trumpet",
        "salsa band",
        "beagle",
        "jacaranda tree",
        "recliner",
        "window seat",
        "Marlins game",
        "grandson",
        "wife",
    ]
    graph.upsert_node("Person", {"id": "user", "name": "Marcus", "relationship": "self"})
    node_ids = ["user"]
    for i in range(n_nodes - 1):
        kind = kinds[i % len(kinds)]
        topic = topics[i % len(topics)]
        node_id = graph.upsert_node(
            kind,
            {
                "id": f"n{i}",
                "name": f"{topic} {i}",
                "notes": f"A fact about {topic} number {i}.",
                "weight": 1.0 + (i % 5) * 0.1,
            },
        )
        node_ids.append(node_id)
        # a light mesh of edges so expand() has real traversal work to do
        if i > 0:
            other = node_ids[max(0, i - 3)]
            other_kind = graph._label_of(other)
            if other_kind == "Thing" and kind in {"Thing", "Activity"}:
                graph.upsert_edge("RELATES_TO", other, node_id, {"weight": 1.0})
        rel_kind = "NEEDS" if kind == "Need" else "LIKES"
        graph.upsert_edge(rel_kind, "user", node_id, {"weight": 1.0, "strength": 0.5})
    return graph


def test_retrieval_completes_under_150ms_at_300_nodes(tmp_path: Path) -> None:
    graph = _build_large_graph(tmp_path, n_nodes=300)
    service = RetrievalService(graph)  # real config.yaml retrieval settings

    # warm the vector cache once, same as production would after the
    # first turn, before measuring steady-state latency
    service.retrieve("warm up the cache")

    _, elapsed_ms = time_retrieval(service, "Did you play trumpet in the band this week?")
    print(f"\nretrieval latency at 300 nodes: {elapsed_ms:.2f} ms")
    assert elapsed_ms < 150.0
