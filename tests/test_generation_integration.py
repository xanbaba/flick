"""The running app must use the real generation prompts and response parser."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from structlog.testing import capture_logs

from backend.app.orchestrator import CANDIDATE_WAIT, IDLE, INTENT_WAIT, Orchestrator
from backend.app.services.voice import SpokenResult
from backend.providers import registry
from backend.providers.base import LLMProvider
from shared.config import EnvSettings, Settings, load_config
from shared.schemas import Selection


@pytest.fixture
def app_orchestrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Orchestrator, AsyncMock]:
    llm = AsyncMock(spec=LLMProvider)
    llm.name = "test"
    monkeypatch.setattr(registry, "_llm", llm)
    from backend.app import main

    config = load_config()
    config.voice.cache_dir = str(tmp_path / "audio")
    settings = Settings(config=config, env=EnvSettings(_env_file=None))
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    orch = main.create_app().state.orchestrator
    # This test bypasses lifespan and has no browser connection.
    orch._playback = None
    return orch, llm


async def test_app_generates_prompted_intents_and_candidates(
    app_orchestrator: tuple[Orchestrator, AsyncMock],
) -> None:
    orch, llm = app_orchestrator
    labels = ["Walk together", "Stay inside", "Which route", "After lunch"]
    candidates = ["Let's walk.", "I'd like to walk together.", "Let's go for a walk after lunch."]
    llm.complete.side_effect = [
        json.dumps({"labels": labels}),
        json.dumps({"candidates": candidates, "grounding": []}),
    ]
    events: list[tuple[str, dict[str, object]]] = []

    async def broadcast(kind: str, payload: dict[str, object]) -> None:
        events.append((kind, payload))
        if kind == "fsm.state" and payload["state"] in (INTENT_WAIT, CANDIDATE_WAIT):
            assert orch.trial_id is not None
            await orch._on_selection(
                Selection(
                    type="input.selection",
                    ts=time.time(),
                    trial_id=orch.trial_id,
                    target_idx=0,
                    confidence=1.0,
                    source="keyboard",
                    algorithm=None,
                )
            )

    orch._broadcast = broadcast
    orch.voice.speak = AsyncMock(
        return_value=SpokenResult(
            text=candidates[0],
            audio=b"",
            voice="browser",
            cached=False,
            latency_ms=0,
        )
    )
    await orch.seed("A test biography", "Alex")
    await orch.submit_utterance("Would you like to go for a walk?")

    assert orch.state == IDLE
    intents = next(payload for kind, payload in events if kind == "conv.intents")
    assert intents["labels"] == labels + ["Cancel"]
    generated = next(payload for kind, payload in events if kind == "conv.candidates")
    assert generated["candidates"] == candidates + ["", "Cancel"]
    orch.voice.speak.assert_awaited_once_with(candidates[0])
    intent_call, candidate_call = llm.complete.await_args_list
    assert "Exactly 4 labels" in intent_call.args[1]
    assert "Would you like to go for a walk?" in intent_call.args[1]
    assert "Alex" in candidate_call.args[1]
    assert 'CHOSEN INTENT: "Walk together"' in candidate_call.args[1]


async def test_app_retries_malformed_intents_with_the_repair_prompt(
    app_orchestrator: tuple[Orchestrator, AsyncMock],
) -> None:
    orch, llm = app_orchestrator
    labels = ["Walk together", "Stay inside", "Which route", "After lunch"]
    llm.complete.side_effect = ["not JSON", json.dumps({"labels": labels})]
    orch._utterance = "Would you like to go for a walk?"
    await orch._ground()
    assert await orch._intent_labels() == labels + ["Cancel"]
    assert llm.complete.await_count == 2
    assert "Your previous response was not valid JSON" in llm.complete.await_args.args[1]


async def test_generation_timeout_is_reported_without_a_second_cloud_request(
    app_orchestrator: tuple[Orchestrator, AsyncMock],
) -> None:
    orch, llm = app_orchestrator
    orch.config.generation.timeout_s = 0.01

    async def stall(*args: object, **kwargs: object) -> str:
        await asyncio.sleep(1)
        raise AssertionError("the request should have been cancelled")

    llm.complete.side_effect = stall
    orch._utterance = "Would you like to go for a walk?"
    await orch._ground()
    with capture_logs() as logs:
        labels = await orch._intent_labels()
    assert labels == ["Yes", "Not now", "Tell me more", "Ask me", "Cancel"]
    assert llm.complete.await_count == 1
    failure = next(log for log in logs if log["event"] == "llm.stage_fallback")
    assert failure["reason"] == "deadline_exceeded"
    assert orch._generation_metadata["intent"] == {
        "source": "fallback",
        "fallback_reason": "deadline_exceeded",
    }
