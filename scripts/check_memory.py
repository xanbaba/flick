"""Explicit real-PostgreSQL acceptance, separate from offline pytest.

Run: uv run python -m scripts.check_memory --env-file .env.pg-test
Use --env-file .env --tiger for the actual sponsor deployment. Only a uniquely
named acceptance profile is written and removed. Providers are labelled test
fixtures: this checks storage and context plumbing, not live LLM quality.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app.services.conversation import ConversationTurn, render_recent
from backend.app.services.generation import GenerationService
from backend.app.services.graph import GraphService
from backend.app.services.onboarding import OnboardingService
from backend.app.services.retrieval import TigerRetrievalService
from backend.app.services.tiger import TigerGraphService
from backend.app.services.tiger_learning import TigerLearningService
from backend.app.services.voice import SpokenResult
from backend.providers import registry
from backend.providers.base import LLMProvider
from backend.providers.embed_minilm import MiniLmEmbeddingProvider
from scripts.import_kuzu_memory import export_kuzu
from shared.config import EnvSettings, Settings, load_config
from shared.logging import get_logger

logger = get_logger(__name__)


class AcceptanceProvider(LLMProvider):
    name = "acceptance_fixture_not_live_llm"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        max_tokens: int = 400,
        timeout: float = 6.0,
    ) -> str:
        self.prompts.append(user)
        if "onboarding stage" in system:
            return json.dumps(
                {
                    "nodes": [
                        {"id": "user", "kind": "Person", "name": "Alex", "relationship": "self"},
                        {"id": "sam", "kind": "Person", "name": "Sam", "relationship": "brother"},
                        {
                            "id": "vacation",
                            "kind": "Memory",
                            "text": "Alex enjoyed a vacation in Lisbon.",
                        },
                    ],
                    "edges": [
                        {"kind": "KNOWS", "source": "user", "target": "sam"},
                        {"kind": "INVOLVES", "source": "vacation", "target": "user"},
                    ],
                }
            )
        if "fact-extraction stage" in system:
            return json.dumps(
                {
                    "nodes": [
                        {
                            "kind": "Memory",
                            "name": "Sam's vacation",
                            "notes": "You visited Rome.",
                            "speaker": "partner",
                            "evidence": "I went on vacation to Rome.",
                            "confidence": 0.95,
                        }
                    ],
                    "edges": [],
                }
            )
        if "partner-identification stage" in system:
            return '{"partner_id":"sam","confidence":0.95,"reason":"acceptance fixture"}'
        if "intent labels" in user:
            return '{"labels":["Wonderful trip","Tell me more","Which vacation","Thanks Sam"]}'
        return json.dumps(
            {
                "candidates": [
                    "It was lovely.",
                    "My Lisbon vacation was lovely.",
                    "I enjoyed my vacation in Lisbon.",
                ],
                "grounding": ["vacation"],
            }
        )


async def check(env_file: str, tiger: bool) -> None:
    settings = EnvSettings(_env_file=env_file)
    dsn = settings.tiger_dsn if tiger else settings.local_pg_dsn
    if not dsn:
        raise RuntimeError("Requested acceptance DSN is not configured")
    config = load_config()
    profile_id = "acceptance_" + uuid.uuid4().hex
    provider = AcceptanceProvider()
    embedder = MiniLmEmbeddingProvider()
    # Force the documented deterministic space for repeatable infrastructure checks.
    embedder._load_attempted = True

    def graph() -> TigerGraphService:
        return TigerGraphService(
            dsn,
            profile_id,
            embedder,
            config.database,
            config.reinforcement,
            destination="tiger" if tiger else "local_postgres",
        )

    service = graph()
    started = time.perf_counter()
    try:
        await service.open()
        onboarding = OnboardingService(service, llm=provider, interval_s=0)
        batches = [
            batch
            async for batch in onboarding.seed(
                "Alex's brother is Sam. Alex enjoyed a vacation in Lisbon.", "Alex"
            )
        ]
        assert sum(len(b.nodes) for b in batches) == 3
        assert (await service.profile())["display_name"] == "Alex"
        retrieval = TigerRetrievalService(service, config.retrieval)
        first = await retrieval.retrieve("How was your vacation?", "sam")
        assert "vacation" in {n.id for n in first.nodes}
        turn = ConversationTurn(
            id=uuid.uuid4().hex,
            partner_id="sam",
            partner_name="Sam",
            user_name="Alex",
            incoming_utterance="I went on vacation to Rome.",
            chosen_intent="Ask about vacation",
            selected_reply="How was your vacation?",
            playback_outcome="completed",
        )
        learning = TigerLearningService(
            service,
            llm=provider,
            embedder=embedder,
            config=config.extraction,
            generation_config=config.generation,
        )
        learned, ok = await learning.learn_turn(turn, "", ["vacation"], [])
        assert ok and len(learned.committed_node_ids) == 1
        fact = await service.get_node(learned.committed_node_ids[0])
        assert fact is not None and fact.fact == 'Sam (partner) said: "I went on vacation to Rome."'
        assert "You visited" not in fact.fact
        weight = (await service.get_node("vacation")).weight
        assert not await service.commit_learning(turn, [], [], ["vacation"], [])
        assert (await service.get_node("vacation")).weight == weight
        await check_failure_boundaries(service, graph)
        await check_import(graph)
        await asyncio.to_thread(check_application, settings, tiger, profile_id + "_app")
        # A graph failure must roll back both reinforcement and the turn record.
        failed = turn.model_copy(update={"id": uuid.uuid4().hex})
        try:
            await service.commit_learning(
                failed,
                [],
                [{"kind": "KNOWS", "source": "missing", "target": "sam"}],
                ["vacation"],
                [],
            )
        except ValueError:
            pass  # Expected rejection is asserted by the rollback checks below.
        else:
            raise AssertionError("Invalid edge was accepted")
        assert (await service.get_node("vacation")).weight == weight
        assert len(await service.recent_turns("sam", 6)) == 1
        # Separate connection/service instance: no in-process cache can satisfy recovery.
        await service.close()
        service = graph()
        await service.open()
        recent = render_recent(await service.recent_turns("sam", 6), config.conversation)
        assert "Rome" in recent and '"partner_said"' in recent
        assert await service.recent_turns(None, 6) == []
        assert await service.node_count() == 4
        retrieval = TigerRetrievalService(service, config.retrieval)
        second = await retrieval.retrieve(
            recent + "\nHow was it?\nChosen intent: Ask about vacation", "sam"
        )
        generation = GenerationService(llm=provider, config=config.generation)
        await generation.generate_intent_result(
            second.context_text, "Sam", "brother", "How was it?", recent
        )
        await generation.generate_candidates(
            "Alex",
            second.context_text,
            [n.id for n in second.nodes],
            "Sam",
            "brother",
            "How was it?",
            "Ask about vacation",
            recent,
        )
        assert all("Rome" in p and "RECENT CONVERSATION" in p for p in provider.prompts[-2:])
        unspoken = turn.model_copy(
            update={
                "id": uuid.uuid4().hex,
                "playback_outcome": "failed",
                "selected_reply": "I visited Mars.",
            }
        )
        learning = TigerLearningService(
            service,
            llm=provider,
            embedder=embedder,
            config=config.extraction,
            generation_config=config.generation,
        )
        await learning.learn_turn(unspoken, recent, ["vacation"], [])
        assert "Mars" not in render_recent(
            await service.recent_turns("sam", 6), config.conversation
        )
        assert (await service.get_node("vacation")).weight == weight
        logger.info(
            "memory.acceptance_passed",
            destination=service.destination,
            elapsed_s=round(time.perf_counter() - started, 3),
            checks="onboarding,pgvector,both_rounds,attribution,atomic_rollback,idempotency,restart,playback",
            providers="scripted acceptance fixtures",
        )
    finally:
        if service._pool is not None:
            async with service._pool.acquire() as conn, conn.transaction():
                for table in ("conversation_turns", "edges", "nodes"):
                    await conn.execute(
                        f"DELETE FROM flick.{table} WHERE profile_id=ANY($1::text[])",
                        [profile_id, profile_id + "_app", profile_id + "_import"],
                    )
                await conn.execute(
                    "DELETE FROM flick.profiles WHERE id=ANY($1::text[])",
                    [profile_id, profile_id + "_app", profile_id + "_import"],
                )
        await service.close()


async def check_failure_boundaries(
    service: TigerGraphService, graph_factory: Callable[[], TigerGraphService]
) -> None:
    original_weight = (await service.get_node("vacation")).weight
    original_timeout = service.database.write_timeout_s
    service.database.write_timeout_s = 0.05
    try:
        try:
            async with service.transaction():
                await service.reinforce(["vacation"], [])
                await asyncio.sleep(0.1)
        except TimeoutError:
            assert not service.available
        else:
            raise AssertionError("Write deadline was not enforced")
    finally:
        service.database.write_timeout_s = original_timeout
    await service.reconcile()
    assert (await service.get_node("vacation")).weight == original_weight
    other = graph_factory()
    other.profile_id += "_isolated"
    try:
        await other.open()
        assert await other.get_node("user") is None
        assert await other.recent_turns("sam", 6) == []
        assert await other.vector_search((await other.embed(["vacation"]))[0], 25) == []
    finally:
        await other.close()


async def check_import(graph_factory: Callable[[], TigerGraphService]) -> None:
    target = graph_factory()
    target.profile_id += "_import"

    def prepare(directory: str) -> dict:
        source, backup = Path(directory) / "source.kuzu", Path(directory) / "rollback.kuzu"
        graph = GraphService(source, embedder=target._embedder)
        try:
            graph.upsert_node("Person", {"id": "user", "name": "Alex", "relationship": "self"})
            graph.upsert_node("Place", {"id": "rome", "name": "Rome", "weight": 2.5})
            graph.upsert_edge("LIKES", "user", "rome", {"weight": 1.4, "count": 3, "strength": 0.7})
        finally:
            graph.close()
        return export_kuzu(source, backup, 10, 10)

    try:
        await target.open()
        with TemporaryDirectory(prefix="flick-import-acceptance-") as directory:
            payload = await asyncio.to_thread(prepare, directory)
            result = await target.seed_profile(payload, "Alex", "", strict=True)
            assert result.node_count == 2 and result.edge_count == 1 and result.dropped == 0
            assert (await target.get_node("rome")).weight == 2.5
            # A changed self identity must roll back instead of silently succeeding.
            try:
                await target.upsert_node(
                    "Person", {"id": "user", "name": "Wrong", "relationship": "self"}
                )
            except ValueError:
                assert (await target.get_node("user")).name == "Alex"
            else:
                raise AssertionError("Profile/self identity diverged")
    finally:
        await target.close()


def check_application(env: EnvSettings, tiger: bool, profile_id: str) -> None:
    """Real app lifespan, HTTP, WebSocket selections, playback and application restart."""
    from backend.app import main as app_main

    config = load_config()
    config.graph.profile_id = profile_id
    config.input.adapter = "keyboard"
    provider = AcceptanceProvider()
    embedder = MiniLmEmbeddingProvider()
    embedder._load_attempted = True
    clean_env = EnvSettings(_env_file=None)
    clean_env.tiger_dsn = env.tiger_dsn if tiger else ""
    clean_env.local_pg_dsn = env.local_pg_dsn if not tiger else ""
    settings = Settings(config=config, env=clean_env)

    async def no_sensor(*args: object) -> None:
        await asyncio.Future()

    def create() -> object:
        app = app_main.create_app(settings=settings)
        app.state.orchestrator._stim_address = None
        return app

    def converse(client: TestClient, ws: object, utterance: str) -> None:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(client.post, "/api/utterance", json={"text": utterance})
            while True:
                message = ws.receive_json()
                if message["type"] == "sys.status" and pending.done():
                    break
                if message["type"] in {"conv.intents", "conv.candidates"}:
                    ws.send_json(
                        {
                            "type": "client.key_press",
                            "ts": time.time(),
                            "key": "1",
                            "trial_id": message["payload"]["trial_id"],
                        }
                    )
                elif message["type"] == "conv.spoken":
                    ws.send_json(
                        {
                            "type": "client.playback_complete",
                            "ts": time.time(),
                            "playback_id": message["payload"]["playback_id"],
                            "outcome": "completed",
                        }
                    )
                elif message["type"] == "fsm.state" and message["payload"]["state"] == "IDLE":
                    if pending.done():
                        break
                    # Initial/reconnect IDLE may precede this turn; a completed turn
                    # has a specific detail, independent of scheduling the HTTP reply.
                    if str(message["payload"]["detail"]).startswith("turn complete"):
                        break
            assert pending.result(timeout=10).status_code == 200

    async def speak(_self: object, text: str) -> SpokenResult:
        return SpokenResult(text=text, voice="browser", cached=False, latency_ms=0, audio=b"")

    with (
        patch.object(registry, "_llm", provider),
        patch.object(registry, "_embedder", embedder),
        patch.object(app_main.SpeechService, "start", AsyncMock()),
        patch.object(app_main.SpeechService, "stop", AsyncMock()),
        patch.object(app_main.VoiceService, "speak", speak),
        patch.object(app_main, "relay_sensor", no_sensor),
    ):
        with TestClient(create()) as client, client.websocket_connect("/ws") as ws:
            assert client.get("/api/onboarding/status").json()["seeded"] is False
            response = client.post(
                "/api/onboarding/seed",
                json={
                    "name": "Alex",
                    "bio": "Alex's brother is Sam. Alex enjoyed a vacation in Lisbon.",
                },
            )
            assert response.status_code == 200, response.text
            assert client.post("/api/partner", json={"partner_id": "sam"}).status_code == 200
            converse(client, ws, "I went on vacation to Rome.")
            assert client.get("/api/health").json()["memory_available"] is True
        with TestClient(create()) as client, client.websocket_connect("/ws") as ws:
            assert client.get("/api/onboarding/status").json()["seeded"] is True
            assert len(client.get("/api/graph").json()["nodes"]) == 4
            assert client.post("/api/partner", json={"partner_id": "sam"}).status_code == 200
            provider.prompts.clear()
            converse(client, ws, "How was it?")
            assert any("RECENT CONVERSATION" in p and "Rome" in p for p in provider.prompts)
    logger.info("memory.application_acceptance_passed", providers="scripted acceptance fixtures")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--tiger", action="store_true")
    args = parser.parse_args()
    asyncio.run(check(args.env_file, args.tiger))


if __name__ == "__main__":
    main()
