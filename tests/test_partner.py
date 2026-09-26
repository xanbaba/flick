"""Tests for backend.app.services.partner (ARCHITECTURE.md section 12.3)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.app.services.graph import GraphService
from backend.app.services.partner import PartnerService
from backend.providers.base import LLMProvider
from backend.providers.llm_static import StaticLLMProvider


class _ScriptedLLM(LLMProvider):
    name = "scripted"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def complete(
        self, system: str, user: str, *, json_mode: bool = False, max_tokens=400, timeout=6.0
    ) -> str:
        del system, user, json_mode, max_tokens, timeout
        self.calls += 1
        return self._responses.pop(0)


def _graph(tmp_path: Path) -> GraphService:
    graph = GraphService(db_path=tmp_path / "kuzu", embedding_dim=384)
    graph.upsert_node("Person", {"id": "user", "name": "Marcus", "relationship": "self"})
    graph.upsert_node(
        "Person",
        {
            "id": "sofia",
            "name": "Sofia",
            "relationship": "daughter",
            "address_terms": ["mija"],
        },
    )
    graph.upsert_node(
        "Person",
        {"id": "priya", "name": "Priya", "relationship": "home nurse"},
    )
    return graph


def test_static_fallback_keeps_shape_and_does_not_raise(tmp_path: Path) -> None:
    service = PartnerService(_graph(tmp_path), llm=StaticLLMProvider())
    result = asyncio.run(service.identify("Hi Dad, it's Sofia."))
    assert result.partner_id is None
    assert result.overridden is False


def test_high_confidence_match_is_kept(tmp_path: Path) -> None:
    payload = json.dumps(
        {"partner_id": "sofia", "confidence": 0.91, "reason": "she said mija's name"}
    )
    service = PartnerService(_graph(tmp_path), llm=_ScriptedLLM([payload]))
    result = asyncio.run(service.identify("Mija is here."))
    assert result.partner_id == "sofia"
    assert result.confidence == 0.91


def test_below_floor_keeps_the_previous_partner(tmp_path: Path) -> None:
    first = json.dumps({"partner_id": "sofia", "confidence": 0.9, "reason": "daughter"})
    low = json.dumps({"partner_id": "priya", "confidence": 0.4, "reason": "unsure"})
    service = PartnerService(_graph(tmp_path), llm=_ScriptedLLM([first, low]))
    assert asyncio.run(service.identify("Hi, it's Sofia.")).partner_id == "sofia"
    kept = asyncio.run(service.identify("hello?"))
    assert kept.partner_id == "sofia"


def test_manual_override_wins_and_persists(tmp_path: Path) -> None:
    payload = json.dumps({"partner_id": "sofia", "confidence": 0.99, "reason": "name"})
    llm = _ScriptedLLM([payload])
    service = PartnerService(_graph(tmp_path), llm=llm)
    overridden = service.set_override("priya")
    assert overridden.partner_id == "priya"
    assert overridden.overridden is True
    again = asyncio.run(service.identify("This is Sofia speaking."))
    assert again.partner_id == "priya"
    assert llm.calls == 0


def test_unknown_id_does_not_replace_the_current_partner(tmp_path: Path) -> None:
    first = json.dumps({"partner_id": "sofia", "confidence": 0.8, "reason": "daughter"})
    bogus = json.dumps({"partner_id": "nobody", "confidence": 0.9, "reason": "guess"})
    service = PartnerService(_graph(tmp_path), llm=_ScriptedLLM([first, bogus, bogus]))
    assert asyncio.run(service.identify("Sofia here.")).partner_id == "sofia"
    assert asyncio.run(service.identify("a stranger")).partner_id == "sofia"
