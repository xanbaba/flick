"""Tests for backend.app.services.generation (ARCHITECTURE.md section 12)."""

from __future__ import annotations

import json

import pytest

from backend.app.services.generation import GenerationService
from backend.providers.base import LLMProvider
from backend.providers.llm_static import StaticLLMProvider
from shared.config import GenerationConfig


class _ScriptedLLM(LLMProvider):
    """Returns each entry in ``responses`` in order, one per call."""

    name = "scripted"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def complete(
        self, system: str, user: str, *, json_mode: bool = False, max_tokens=400, timeout=6.0
    ) -> str:
        del system, json_mode, max_tokens, timeout
        self.calls.append(user)
        return self._responses.pop(0)


@pytest.fixture
def config() -> GenerationConfig:
    return GenerationConfig(n_intents=4, n_candidates=3, max_tokens=400, timeout_s=6.0)


def test_generate_intents_with_static_fallback_never_raises(config: GenerationConfig) -> None:
    import asyncio

    svc = GenerationService(llm=StaticLLMProvider(), config=config)
    labels = asyncio.run(
        svc.generate_intents(
            context="- fact one\n- fact two",
            partner_name="Sofia",
            partner_relationship="daughter",
            utterance="How are you?",
        )
    )
    assert len(labels) == 4
    assert all(isinstance(label, str) and label for label in labels)


def test_generate_intents_parses_well_formed_json(config: GenerationConfig) -> None:
    import asyncio

    good = json.dumps({"labels": ["Yes", "No thanks", "Tell me more", "Ask Sofia"]})
    llm = _ScriptedLLM([good])
    svc = GenerationService(llm=llm, config=config)
    labels = asyncio.run(
        svc.generate_intents(
            context="- fact", partner_name="Sofia", partner_relationship="daughter", utterance="hi"
        )
    )
    assert labels == ["Yes", "No thanks", "Tell me more", "Ask Sofia"]
    assert len(llm.calls) == 1


def test_generate_intents_repairs_once_then_succeeds(config: GenerationConfig) -> None:
    import asyncio

    bad = "not json at all"
    good = json.dumps({"labels": ["Yes", "No", "Later", "Why"]})
    llm = _ScriptedLLM([bad, good])
    svc = GenerationService(llm=llm, config=config)
    labels = asyncio.run(
        svc.generate_intents(
            context="- fact", partner_name="Sofia", partner_relationship="daughter", utterance="hi"
        )
    )
    assert labels == ["Yes", "No", "Later", "Why"]
    assert len(llm.calls) == 2
    assert "not json at all" in llm.calls[1]  # repair prompt includes the bad response


def test_generate_intents_falls_back_after_two_failures(config: GenerationConfig) -> None:
    import asyncio

    llm = _ScriptedLLM(["nope", "still nope"])
    svc = GenerationService(llm=llm, config=config)
    labels = asyncio.run(
        svc.generate_intents(
            context="- fact", partner_name="Sofia", partner_relationship="daughter", utterance="hi"
        )
    )
    assert len(labels) == 4
    assert len(llm.calls) == 2


def test_generate_intents_rejects_wrong_shape_and_falls_back(config: GenerationConfig) -> None:
    import asyncio

    too_few = json.dumps({"labels": ["Yes", "No"]})
    llm = _ScriptedLLM([too_few, too_few])
    svc = GenerationService(llm=llm, config=config)
    labels = asyncio.run(
        svc.generate_intents(
            context="- fact", partner_name="Sofia", partner_relationship="daughter", utterance="hi"
        )
    )
    assert len(labels) == 4  # local placeholder, not the malformed 2-label response


def test_generate_candidates_with_static_fallback_never_raises(config: GenerationConfig) -> None:
    import asyncio

    svc = GenerationService(llm=StaticLLMProvider(), config=config)
    result = asyncio.run(
        svc.generate_candidates(
            user_name="Marcus",
            context="- Rosie is your dog.",
            context_node_ids=["rosie"],
            partner_name="Sofia",
            partner_relationship="daughter",
            utterance="Did you walk the dog?",
            intent="Yes",
        )
    )
    assert result.candidates == ["Yes"]
    assert result.grounding == []
    assert result.source == "fallback"
    assert result.fallback_reason == "no_provider"


def test_generate_candidates_drops_grounding_ids_not_in_context(config: GenerationConfig) -> None:
    import asyncio

    good = json.dumps(
        {
            "candidates": ["Yes.", "Yeah, I did.", "I took Rosie out this morning, actually."],
            "grounding": ["rosie", "made_up_id"],
        }
    )
    llm = _ScriptedLLM([good])
    svc = GenerationService(llm=llm, config=config)
    result = asyncio.run(
        svc.generate_candidates(
            user_name="Marcus",
            context="- Rosie is your dog.",
            context_node_ids=["rosie"],
            partner_name="Sofia",
            partner_relationship="daughter",
            utterance="Did you walk the dog?",
            intent="Yes",
        )
    )
    assert result.candidates == ["Yes.", "Yeah, I did.", "I took Rosie out this morning, actually."]
    assert result.grounding == ["rosie"]  # made_up_id silently dropped, not a failure


def test_generate_candidates_strips_markdown_fences(config: GenerationConfig) -> None:
    import asyncio

    payload = json.dumps({"candidates": ["Yes.", "Yeah.", "Sure, I did."], "grounding": ["rosie"]})
    fenced = f"```json\n{payload}\n```"
    llm = _ScriptedLLM([fenced])
    svc = GenerationService(llm=llm, config=config)
    result = asyncio.run(
        svc.generate_candidates(
            user_name="Marcus",
            context="- Rosie is your dog.",
            context_node_ids=["rosie"],
            partner_name="Sofia",
            partner_relationship="daughter",
            utterance="Did you walk the dog?",
            intent="Yes",
        )
    )
    assert result.grounding == ["rosie"]
