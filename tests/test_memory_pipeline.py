"""Exercise real application wiring, storage and keyboard messages over two turns."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from backend.app.services.speech import SpeechService
from backend.providers import registry
from backend.providers.base import EmbeddingProvider, LLMProvider
from backend.providers.embed_minilm import _hashing_trick_embed
from shared.config import EnvSettings, Settings, load_config


class RecordingEmbeddings(EmbeddingProvider):
    name = "test_hash"
    dim = 384

    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        self.texts.extend(texts)
        return _hashing_trick_embed(texts, self.dim)


class ConversationProvider(LLMProvider):
    name = "scripted_test_only"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_seed = False
        self.fail_learning = False
        self.fail_candidates = False
        self.learned = False
        self.seed_delay = 0.0

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 400,
        timeout: float = 6.0,
    ) -> str:
        self.calls.append((system, user))
        if "onboarding stage" in system:
            await asyncio.sleep(self.seed_delay)
            if self.fail_seed:
                raise TimeoutError("test provider unavailable")
            if "expansion pass" in user:
                return '{"nodes":[],"edges":[]}'
            return json.dumps(
                {
                    "nodes": [
                        {
                            "id": "sam",
                            "kind": "Person",
                            "name": "Sam",
                            "relationship": "brother",
                            "address_terms": ["buddy"],
                            "notes": "Sam is your brother.",
                        },
                        {
                            "id": "chair",
                            "kind": "Thing",
                            "name": "blue chair",
                            "notes": "You like your blue chair.",
                        },
                    ],
                    "edges": [
                        {"kind": "KNOWS", "source": "user", "target": "sam"},
                        {"kind": "LIKES", "source": "user", "target": "chair"},
                    ],
                }
            )
        if "partner-identification stage" in system:
            return '{"partner_id":"sam","confidence":0.95,"reason":"introduced himself"}'
        if "fact-extraction stage" in system:
            if self.fail_learning:
                raise TimeoutError("test extraction unavailable")
            if self.learned:
                return '{"nodes":[],"edges":[]}'
            self.learned = True
            return json.dumps(
                {
                    "nodes": [
                        {
                            "kind": "Thing",
                            "name": "mint tea",
                            "notes": "You now have mint tea.",
                            "confidence": 0.95,
                        }
                    ],
                    "edges": [
                        {
                            "kind": "LIKES",
                            "source": "user",
                            "target_name": "mint tea",
                            "confidence": 0.9,
                        }
                    ],
                }
            )
        if "Exactly 4 labels" in user:
            if "You now have mint tea." in user:
                return '{"labels":["Have tea","Not now","Which tea","Thanks Sam"]}'
            return '{"labels":["Sit comfortably","Not now","Tell me more","Thanks Sam"]}'
        if self.fail_candidates:
            raise TimeoutError("test candidate provider unavailable")
        tea = re.search(r"\[([^]]+)\] You now have mint tea", user)
        return json.dumps(
            {
                "candidates": [
                    "Mint tea, please.",
                    "I'd like my mint tea, buddy.",
                    "I'd like some of my mint tea, buddy.",
                ]
                if tea
                else [
                    "My blue chair, please.",
                    "I'd like my blue chair, buddy.",
                    "I'd like to sit in my blue chair, buddy.",
                ],
                "grounding": ["user", tea.group(1) if tea else "chair", "invented_id"],
            }
        )


ApplicationFactory = tuple[Callable[[], FastAPI], ConversationProvider, RecordingEmbeddings]


async def no_sensor(*args: Any) -> None:
    await asyncio.Event().wait()


@pytest.fixture
def application(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Callable[[], FastAPI], ConversationProvider, RecordingEmbeddings]:
    llm = ConversationProvider()
    embedder = RecordingEmbeddings()
    monkeypatch.setattr(registry, "_llm", llm)
    monkeypatch.setattr(registry, "_embedder", embedder)
    from backend.app import main

    config = load_config()
    config.graph.db_path = str(tmp_path / "graph")
    config.voice.cache_dir = str(tmp_path / "audio")
    settings = Settings(config=config, env=EnvSettings(_env_file=None))
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "configure_logging", lambda: None)
    monkeypatch.setattr(main, "relay_sensor", no_sensor)
    monkeypatch.setattr(SpeechService, "start", AsyncMock())
    monkeypatch.setattr(SpeechService, "stop", AsyncMock())

    def create() -> FastAPI:
        app = main.create_app()
        app.state.orchestrator._stim_address = None
        app.state.orchestrator.wait_timeout_s = 3.0
        return app

    return create, llm, embedder


def wait_for_state(app: FastAPI, state: str) -> None:
    deadline = time.monotonic() + 5
    while app.state.orchestrator.state != state:
        if time.monotonic() > deadline:
            pytest.fail(f"expected {state}; found {app.state.orchestrator.state}")
        time.sleep(0.005)


def turn(client: TestClient, app: FastAPI, ws: WebSocketTestSession, utterance: str) -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        response = executor.submit(client.post, "/api/utterance", json={"text": utterance})
        wait_for_state(app, "INTENT_WAIT")
        ws.send_json({"type": "client.key_press", "ts": time.time(), "key": "1"})
        wait_for_state(app, "CANDIDATE_WAIT")
        ws.send_json({"type": "client.key_press", "ts": time.time(), "key": "2"})
        assert response.result(timeout=10).status_code == 200
    assert app.state.orchestrator.state == "IDLE"


def watch(app: FastAPI) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    original = app.state.hub.broadcast

    async def broadcast(kind: str, payload: dict[str, Any]) -> None:
        events.append((kind, payload))
        await original(kind, payload)

    app.state.hub.broadcast = broadcast
    return events


def test_two_turn_memory_pipeline_and_restart(application: ApplicationFactory) -> None:
    create, llm, embeddings = application
    app = create()
    events = watch(app)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["payload"] == {"nodes": [], "edges": []}
        assert client.get("/api/onboarding/status").json() == {"seeded": False, "node_count": 0}
        response = client.post(
            "/api/onboarding/seed",
            json={
                "name": "Alex",
                "bio": "Alex has a brother Sam, called buddy, and likes a blue chair.",
            },
        )
        assert response.json() == {"seeded": True, "node_count": 3}
        assert any(kind == "graph.bloom" for kind, _ in events)
        initial = client.get("/api/graph").json()
        assert {n["id"] for n in initial["nodes"]} == {"user", "sam", "chair"}
        assert client.post("/api/partner", json={"partner_id": "unknown"}).status_code == 422
        assert client.post("/api/partner", json={"partner_id": "sam"}).status_code == 200
        assert (
            client.post("/api/onboarding/seed", json={"name": "Other", "bio": "Other"}).status_code
            == 409
        )

        utterance = "Sam here. I bought mint tea for you. Shall I get your chair?"
        turn(client, app, ws, utterance)
        assert utterance in embeddings.texts
        assert f"{utterance}\nChosen intent: Sit comfortably" in embeddings.texts
        candidates = [payload for kind, payload in events if kind == "conv.candidates"][-1]
        assert candidates["grounding"] == ["user", "chair"]
        assert any(kind == "conv.spoken" for kind, _ in events)
        generated_prompts = [prompt for _, prompt in llm.calls if "Produce exactly 3" in prompt]
        assert "[chair]" in generated_prompts[-1]
        assert "buddy" in generated_prompts[-1] and "Sam (brother)" in generated_prompts[-1]
        after = client.get("/api/graph").json()
        tea = next(node for node in after["nodes"] if node["label"] == "mint tea")
        assert next(n for n in after["nodes"] if n["id"] == "chair")["weight"] == pytest.approx(1.1)
        assert next(e for e in after["edges"] if e["target"] == "chair")["weight"] == pytest.approx(
            1.15
        )
        assert any(e["target"] == tea["id"] for e in after["edges"])
        assert any(
            kind == "graph.bloom" and any(n["id"] == tea["id"] for n in p["nodes"])
            for kind, p in events
        )

        turn(client, app, ws, "What tea do I have now?")
        second_intent = [p for _, p in llm.calls if "Exactly 4 labels" in p][-1]
        second_candidates = [p for _, p in llm.calls if "Produce exactly 3" in p][-1]
        assert "You now have mint tea." in second_intent
        assert f"[{tea['id']}] You now have mint tea." in second_candidates
        second_grounding = [p["grounding"] for kind, p in events if kind == "conv.candidates"][-1]
        assert tea["id"] in second_grounding
        assert "mint tea" in [p["text"] for kind, p in events if kind == "conv.spoken"][-1]
        assert client.get("/api/onboarding/status").json()["node_count"] == 4

    restarted = create()
    with TestClient(restarted) as client, client.websocket_connect("/ws") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "graph.snapshot"
        assert tea["id"] in {n["id"] for n in snapshot["payload"]["nodes"]}
        assert client.get("/api/onboarding/status").json() == {"seeded": True, "node_count": 4}
        assert restarted.state.orchestrator.state == "IDLE"
        assert restarted.state.orchestrator._user_name == "Alex"
        turn(client, restarted, ws, "What tea do I have now?")
        assert "You now have mint tea." in [p for _, p in llm.calls if "Exactly 4 labels" in p][-1]


def test_failed_custom_seed_is_retryable(application: ApplicationFactory) -> None:
    create, llm, _ = application
    llm.fail_seed = True
    app = create()
    with TestClient(app) as client:
        response = client.post(
            "/api/onboarding/seed", json={"name": "Alex", "bio": "Alex likes tea"}
        )
        assert response.status_code == 503
        assert "try again" in response.json()["detail"]
        assert client.get("/api/graph").json() == {"nodes": [], "edges": []}
        assert client.get("/api/onboarding/status").json()["seeded"] is False
        assert app.state.orchestrator.state == "UNSEEDED"


def test_concurrent_seed_is_rejected(application: ApplicationFactory) -> None:
    create, llm, _ = application
    llm.seed_delay = 0.1
    app = create()
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            client.post, "/api/onboarding/seed", json={"name": "Alex", "bio": "Alex"}
        )
        deadline = time.monotonic() + 5
        while not app.state.orchestrator._seed_lock.locked():
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert (
            client.post("/api/onboarding/seed", json={"name": "Other", "bio": "Other"}).status_code
            == 409
        )
        assert first.result(timeout=10).status_code == 200


def test_writeback_failure_returns_idle_without_bloom(application: ApplicationFactory) -> None:
    create, llm, _ = application
    app = create()
    events = watch(app)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert (
            client.post("/api/onboarding/seed", json={"name": "Alex", "bio": "Alex"}).status_code
            == 200
        )
        events.clear()
        llm.fail_learning = True
        turn(client, app, ws, "Sam here. Would you like your chair?")
        assert not any(kind == "graph.bloom" for kind, _ in events)
        assert client.get("/api/onboarding/status").json()["node_count"] == 3
        state = [p for kind, p in events if kind == "fsm.state"][-1]
        assert state["state"] == "IDLE" and "memory update unavailable" in state["detail"]


def test_candidate_provider_failure_keeps_grounded_fallback(
    application: ApplicationFactory,
) -> None:
    create, llm, _ = application
    app = create()
    events = watch(app)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert (
            client.post("/api/onboarding/seed", json={"name": "Alex", "bio": "Alex"}).status_code
            == 200
        )
        llm.fail_candidates = True
        llm.learned = True
        turn(client, app, ws, "Sam here. Would you like your chair?")
        candidates = [p for kind, p in events if kind == "conv.candidates"][-1]
        assert candidates["grounding"]
        assert set(candidates["grounding"]) <= {"user", "sam", "chair"}
        assert len(candidates["candidates"]) == 4
