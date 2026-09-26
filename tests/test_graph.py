"""Tests for backend.app.services.graph (ARCHITECTURE.md section 10)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.app.services.graph import GraphService, NodeRef


@pytest.fixture
def graph(tmp_path: Path) -> GraphService:
    return GraphService(db_path=tmp_path / "kuzu", embedding_dim=384)


def test_ensure_schema_is_idempotent(graph: GraphService) -> None:
    graph.ensure_schema()
    graph.ensure_schema()
    assert graph.node_count() == 0


def test_upsert_node_roundtrips_through_snapshot(graph: GraphService) -> None:
    node_id = graph.upsert_node("Person", {"id": "user", "name": "Marcus", "relationship": "self"})
    assert node_id == "user"
    nodes, edges = graph.snapshot()
    assert len(nodes) == 1
    assert nodes[0].label == "Marcus"
    assert nodes[0].kind == "Person"
    assert edges == []


def test_upsert_node_generates_id_when_absent(graph: GraphService) -> None:
    node_id = graph.upsert_node("Thing", {"name": "recliner"})
    assert node_id.startswith("thing_")
    assert graph.node_count() == 1


def test_upsert_node_is_idempotent_on_id(graph: GraphService) -> None:
    graph.upsert_node("Place", {"id": "p1", "name": "window seat", "weight": 1.0})
    graph.upsert_node("Place", {"id": "p1", "name": "window seat", "weight": 2.0})
    assert graph.node_count() == 1
    nodes, _ = graph.snapshot()
    assert nodes[0].weight == 2.0


def test_memory_node_label_truncates_to_60_chars(graph: GraphService) -> None:
    long_text = "x" * 200
    graph.upsert_node("Memory", {"id": "m1", "text": long_text})
    nodes, _ = graph.snapshot()
    assert nodes[0].label == long_text[:60]
    assert len(nodes[0].label) == 60


def test_upsert_edge_connects_valid_pair(graph: GraphService) -> None:
    graph.upsert_node("Person", {"id": "user", "name": "Marcus"})
    graph.upsert_node("Thing", {"id": "rosie", "name": "Rosie"})
    edge_id = graph.upsert_edge("LIKES", "user", "rosie", {"weight": 0.9, "strength": 0.8})
    assert edge_id == "LIKES:user->rosie"
    _, edges = graph.snapshot()
    assert len(edges) == 1
    assert edges[0].source == "user"
    assert edges[0].target == "rosie"


def test_upsert_edge_rejects_invalid_pair(graph: GraphService) -> None:
    graph.upsert_node("Thing", {"id": "t1", "name": "chair"})
    graph.upsert_node("Need", {"id": "n1", "name": "comfort"})
    with pytest.raises(ValueError):
        graph.upsert_edge("KNOWS", "t1", "n1", {})


def test_upsert_edge_is_idempotent_and_accumulates_count(graph: GraphService) -> None:
    graph.upsert_node("Person", {"id": "user", "name": "Marcus"})
    graph.upsert_node("Thing", {"id": "rosie", "name": "Rosie"})
    graph.upsert_edge("LIKES", "user", "rosie", {"weight": 0.5})
    graph.upsert_edge("LIKES", "user", "rosie", {"weight": 0.9})
    _, edges = graph.snapshot()
    assert len(edges) == 1
    assert edges[0].weight == 0.9


def test_vector_search_returns_closest_by_cosine(graph: GraphService) -> None:
    graph.upsert_node("Thing", {"id": "coffee", "name": "strong black coffee"})
    graph.upsert_node("Thing", {"id": "trumpet", "name": "trumpet in a salsa band"})
    graph.upsert_node("Place", {"id": "window", "name": "window seat jacaranda tree"})

    from backend.providers.registry import get_embedding_provider

    q = get_embedding_provider().embed(["strong coffee"])[0]
    results = graph.vector_search(np.asarray(q), k=2)
    assert len(results) == 2
    assert results[0].id == "coffee"


def test_vector_search_cache_invalidates_on_write(graph: GraphService) -> None:
    from backend.providers.registry import get_embedding_provider

    q = get_embedding_provider().embed(["rosie the beagle"])[0]
    assert graph.vector_search(np.asarray(q), k=5) == []

    graph.upsert_node("Thing", {"id": "rosie", "name": "rosie the beagle"})
    results = graph.vector_search(np.asarray(q), k=5)
    assert len(results) == 1
    assert results[0].id == "rosie"


def test_expand_includes_seeds_and_one_hop_neighbours(graph: GraphService) -> None:
    graph.upsert_node("Person", {"id": "user", "name": "Marcus", "weight": 1.0})
    graph.upsert_node("Thing", {"id": "rosie", "name": "Rosie", "weight": 3.0})
    graph.upsert_node("Place", {"id": "vet", "name": "the vet", "weight": 0.5})
    graph.upsert_edge("LIKES", "user", "rosie", {"weight": 1.0})
    graph.upsert_edge("LOCATED_AT", "rosie", "vet", {"weight": 1.0})

    seeds = [NodeRef(id="user", kind="Person", name="Marcus", weight=1.0)]
    expanded = graph.expand(seeds, hops=2, cap=10)
    ids = {n.id for n in expanded}
    assert {"user", "rosie", "vet"} <= ids
    # higher weight nodes sort first among the non-seed results
    assert expanded[0].id in {"user", "rosie"}


def test_expand_respects_cap(graph: GraphService) -> None:
    graph.upsert_node("Person", {"id": "user", "name": "Marcus", "weight": 1.0})
    for i in range(5):
        tid = f"t{i}"
        graph.upsert_node("Thing", {"id": tid, "name": f"thing {i}", "weight": float(i)})
        graph.upsert_edge("LIKES", "user", tid, {"weight": 1.0})

    seeds = [NodeRef(id="user", kind="Person", name="Marcus", weight=1.0)]
    expanded = graph.expand(seeds, hops=1, cap=3)
    assert len(expanded) == 3


def test_reinforce_bumps_weight_and_caps_at_max(graph: GraphService) -> None:
    graph.upsert_node("Thing", {"id": "rosie", "name": "Rosie", "weight": 4.95})
    graph.reinforce(node_ids=["rosie"], edge_ids=[])
    nodes, _ = graph.snapshot()
    assert nodes[0].weight == pytest.approx(5.0)


def test_reinforce_bumps_edge_weight(graph: GraphService) -> None:
    graph.upsert_node("Person", {"id": "user", "name": "Marcus"})
    graph.upsert_node("Thing", {"id": "rosie", "name": "Rosie"})
    edge_id = graph.upsert_edge("LIKES", "user", "rosie", {"weight": 1.0})
    graph.reinforce(node_ids=[], edge_ids=[edge_id])
    _, edges = graph.snapshot()
    assert edges[0].weight == pytest.approx(1.15)


def test_people_returns_person_rows(graph: GraphService) -> None:
    graph.upsert_node(
        "Person",
        {"id": "user", "name": "Marcus", "relationship": "self", "address_terms": []},
    )
    graph.upsert_node(
        "Person",
        {
            "id": "sofia",
            "name": "Sofia",
            "relationship": "daughter",
            "address_terms": ["mija"],
        },
    )
    people = {p.id: p for p in graph.people()}
    assert people["sofia"].address_terms == ["mija"]
    assert people["user"].relationship == "self"


def test_node_count(graph: GraphService) -> None:
    assert graph.node_count() == 0
    graph.upsert_node("Person", {"id": "user", "name": "Marcus"})
    graph.upsert_node("Thing", {"id": "rosie", "name": "Rosie"})
    assert graph.node_count() == 2


def test_seed_from_json_basic(graph: GraphService) -> None:
    payload = {
        "nodes": [
            {"id": "user", "kind": "Person", "name": "Marcus", "relationship": "self"},
            {"id": "rosie", "kind": "Thing", "name": "Rosie", "category": "pet"},
        ],
        "edges": [
            {"kind": "LIKES", "source": "user", "target": "rosie", "weight": 1.0},
        ],
    }
    result = graph.seed_from_json(payload)
    assert result.node_count == 2
    assert result.edge_count == 1
    assert result.dropped == 0
    assert graph.node_count() == 2


def test_seed_from_json_drops_malformed_entries(graph: GraphService) -> None:
    payload = {
        "nodes": [
            {"id": "user", "kind": "Person", "name": "Marcus"},
            {"kind": "NotAKind", "name": "broken"},
            {"kind": "Thing"},  # no display text
        ],
        "edges": [
            {"kind": "LIKES", "source": "user", "target": "does_not_exist"},
            {"kind": "NOT_A_KIND", "source": "user", "target": "user"},
        ],
    }
    result = graph.seed_from_json(payload)
    assert result.node_count == 1
    assert result.edge_count == 0
    assert result.dropped == 4
