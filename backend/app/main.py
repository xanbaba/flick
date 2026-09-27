"""FastAPI entry point for P3 (ARCHITECTURE.md sections 3.2 and 6.8).

Boots with an empty .env: providers resolve to their offline last
links. Generation and memory services share an application-scoped persistent
graph. Knowledge services are constructed during application startup.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel

from backend.app.orchestrator import IDLE, UNSEEDED, Orchestrator, SeedConflictError
from backend.app.services.analytics import AnalyticsService
from backend.app.services.cost import CostTracker
from backend.app.services.cost import flows as recorded_flows
from backend.app.services.extraction import ExtractionService
from backend.app.services.generation import GenerationService
from backend.app.services.graph import GraphService
from backend.app.services.onboarding import OnboardingService, SeedUnavailableError
from backend.app.services.partner import PartnerService
from backend.app.services.retrieval import RetrievalService
from backend.app.services.spectator import SpectatorService
from backend.app.services.speech import SpeechService
from backend.app.services.telemetry import TelemetryService
from backend.app.services.voice import VoiceService
from backend.app.services.worker import MemoryWorker, run_memory
from backend.app.ws import Hub, relay_sensor, serve
from backend.providers.registry import get_embedding_provider, health_snapshot
from inputs.base import InputSource
from inputs.keyboard import KeyboardInput
from inputs.replay import ReplayInput
from inputs.ssvep import SsvepInput
from shared.config import get_settings
from shared.logging import configure_logging, get_logger

logger = get_logger(__name__)

STIM_ADDRESS = "tcp://127.0.0.1:5556"
SENSOR_ADDRESS = "tcp://127.0.0.1:5555"


class SeedBody(BaseModel):
    bio: str
    name: str


class PartnerBody(BaseModel):
    partner_id: str


class UtteranceBody(BaseModel):
    text: str


class ModeBody(BaseModel):
    mode: str


class InputBody(BaseModel):
    adapter: str


class CuedBlockBody(BaseModel):
    n_trials: int = 20
    train_etrca: bool = False


class LocalModeBody(BaseModel):
    enabled: bool


class PurgeBody(BaseModel):
    scope: str


def build_input(adapter: str, n_targets: int) -> InputSource:
    if adapter == "keyboard":
        return KeyboardInput(n_targets=n_targets)
    if adapter == "ssvep":
        return SsvepInput(n_targets=n_targets)
    if adapter == "replay":
        return ReplayInput(n_targets=n_targets)
    raise ValueError(f"unknown input adapter: {adapter}")


def create_app() -> FastAPI:
    settings = get_settings()
    config = settings.config
    hub = Hub()
    telemetry = TelemetryService(
        queue_maxsize=config.telemetry.queue_maxsize,
        flush_interval_ms=config.telemetry.flush_interval_ms,
        flush_batch=config.telemetry.flush_batch,
        dsn=settings.env.timescale_dsn,
    )
    analytics = AnalyticsService()
    spectator = SpectatorService(url=settings.env.spectator_url)
    voice = VoiceService(
        config.voice.cache_dir,
        cache_first=config.voice.cache_first,
        voice_id=settings.env.elevenlabs_voice_id or None,
    )
    flags = {"local_mode": config.privacy.local_mode or settings.env.local_mode}
    input_box: dict[str, InputSource] = {
        "source": build_input(config.input.adapter, config.mode.targets)
    }

    orchestrator_box: dict[str, Orchestrator] = {}

    async def on_transcript(transcript: Any) -> None:
        await orchestrator_box["orch"].on_transcript(transcript)

    speech = SpeechService(on_transcript)

    async def broadcast(message_type: str, payload: dict[str, object]) -> None:
        await hub.broadcast(message_type, payload)

    orchestrator = Orchestrator(
        input_source=input_box["source"],
        broadcast=broadcast,
        voice=voice,
        speech=speech,
        cost=CostTracker(config.privacy.price_table),
        config=config,
        generation=GenerationService(config=config.generation),
        stim_address=STIM_ADDRESS,
    )
    orchestrator_box["orch"] = orchestrator

    background: list[asyncio.Task[None]] = []

    def status_payload() -> dict[str, object]:
        source = orchestrator.input
        return {
            "input_source": source.name,
            "input_badge": source.badge,
            "source": config.mode.source,
            "connected": bool(
                source.status().get("connected", source.status().get("started", False))
            ),
            "replay": source.name == "replay",
            "local_mode": flags["local_mode"],
            "profile": config.stimulus.profile,
            "measured_refresh_hz": None,
            "providers": health_snapshot(),
            "stimulus_integrity": None,
            "telemetry_dropped": telemetry.dropped_count,
        }

    async def snapshot_payload() -> dict[str, object]:
        return await orchestrator.snapshot()

    async def status_loop() -> None:
        while True:
            await asyncio.sleep(1.0)
            await hub.broadcast("sys.status", status_payload())

    async def analytics_loop() -> None:
        while True:
            await asyncio.sleep(2.0)
            await hub.broadcast("analytics.summary", analytics.summary().model_dump())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        worker = MemoryWorker()
        graph_service: GraphService | None = None
        try:
            graph_service = await worker.run(
                GraphService,
                config.graph.db_path,
                config.graph.embedding_dim,
                get_embedding_provider(),
            )
            orchestrator.graph = graph_service
            orchestrator.worker = worker
            orchestrator.retrieval = RetrievalService(graph_service, config=config.retrieval)
            orchestrator.onboarding = OnboardingService(
                graph_service,
                worker=worker,
                config=config.generation,
            )
            orchestrator.partner = PartnerService(
                graph_service,
                worker=worker,
                config=config.generation,
            )
            orchestrator.extraction = ExtractionService(
                graph_service,
                config=config.extraction,
                worker=worker,
                generation_config=config.generation,
            )
            await telemetry.start()
            await orchestrator.start()
            background.append(asyncio.create_task(status_loop()))
            background.append(asyncio.create_task(analytics_loop()))
            background.append(asyncio.create_task(relay_sensor(hub, SENSOR_ADDRESS)))
            logger.info("backend.started", adapter=config.input.adapter)
            yield
        finally:
            for task in background:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)
            background.clear()
            await orchestrator.stop()
            await telemetry.stop()
            if graph_service is not None:
                await worker.run(graph_service.close)
            orchestrator.graph = None
            await worker.close()

    app = FastAPI(lifespan=lifespan)
    app.state.orchestrator = orchestrator
    app.state.hub = hub
    app.state.telemetry = telemetry
    app.state.analytics = analytics
    app.state.spectator = spectator
    app.state.flags = flags

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {"ok": True, "state": orchestrator.state, "providers": health_snapshot()}

    @app.get("/api/graph")
    async def graph() -> dict[str, object]:
        return await snapshot_payload()

    @app.post("/api/onboarding/seed")
    async def seed(body: SeedBody) -> dict[str, object]:
        if not body.bio.strip() or not body.name.strip():
            raise HTTPException(422, "Name and biography must not be blank")
        try:
            return await orchestrator.seed(body.bio, body.name)
        except SeedConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except SeedUnavailableError as exc:
            raise HTTPException(503, str(exc)) from exc
        except Exception as exc:
            logger.warning("onboarding.seed_failed", error_type=type(exc).__name__)
            raise HTTPException(503, "Memory storage is unavailable. Please try again.") from exc

    @app.get("/api/onboarding/status")
    async def onboarding_status() -> dict[str, object]:
        return await orchestrator.onboarding_status()

    @app.post("/api/partner")
    async def partner(body: PartnerBody) -> dict[str, object]:
        if orchestrator.partner is None:
            raise HTTPException(503, "Memory services are unavailable")
        try:
            await run_memory(
                orchestrator.worker, orchestrator.partner.set_override, body.partner_id
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"partner_id": body.partner_id}

    @app.post("/api/utterance")
    async def utterance(body: UtteranceBody) -> dict[str, object]:
        await orchestrator.submit_utterance(body.text)
        return {"state": orchestrator.state, "trial_id": orchestrator.trial_id}

    @app.post("/api/mode")
    async def mode(body: ModeBody) -> dict[str, str]:
        if body.mode not in ("intent", "speller"):
            return {"mode": orchestrator.mode}
        orchestrator.mode = body.mode
        return {"mode": orchestrator.mode}

    @app.post("/api/input")
    async def swap_input(body: InputBody) -> dict[str, str]:
        if orchestrator.state not in (IDLE, UNSEEDED):
            return {"adapter": orchestrator.input.name, "error": "busy"}
        try:
            replacement = build_input(body.adapter, config.mode.targets)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            await orchestrator.swap_input(replacement)
        except ValueError:
            return {"adapter": orchestrator.input.name, "error": "busy"}
        except Exception as exc:
            logger.warning("input.switch_failed", error_type=type(exc).__name__)
            raise HTTPException(503, "Input adapter could not start. Please try again.") from exc
        await hub.broadcast("sys.status", status_payload())
        return {"adapter": replacement.name}

    @app.post("/api/cued_block/start")
    async def cued_block(body: CuedBlockBody) -> dict[str, object]:
        # TODO: drive stim.show_targets with cue_idx once P2 exists, and
        # record selections.cued_idx (section 18.4). Nothing here invents
        # accuracy; the block is accepted and not simulated.
        logger.info("cued_block.requested", n_trials=body.n_trials, train_etrca=body.train_etrca)
        return {"accepted": True, "n_trials": body.n_trials, "train_etrca": body.train_etrca}

    @app.get("/api/session/latest")
    async def session_latest() -> dict[str, object]:
        directory = Path(config.recording.dir)
        if not directory.is_dir():
            return {"path": None}
        files = sorted(directory.glob("*.npz"))
        return {"path": str(files[-1]) if files else None}

    @app.get("/api/analytics/summary")
    async def analytics_summary() -> dict[str, object]:
        return analytics.summary().model_dump()

    @app.post("/api/privacy/local_mode")
    async def local_mode(body: LocalModeBody) -> dict[str, bool]:
        flags["local_mode"] = body.enabled
        return {"local_mode": body.enabled}

    @app.get("/api/privacy/flows")
    async def privacy_flows() -> dict[str, object]:
        return {"flows": recorded_flows()}

    @app.post("/api/privacy/purge")
    async def purge(body: PurgeBody) -> dict[str, str]:
        if body.scope == "all":
            cache = Path(config.voice.cache_dir)
            if cache.is_dir():
                for cached in cache.glob("*"):
                    if cached.is_file():
                        cached.unlink()
        return {"scope": body.scope}

    @app.get("/api/spectator/link")
    async def spectator_link() -> dict[str, object]:
        return spectator.link()

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await serve(
            websocket,
            hub=hub,
            input_source=lambda: orchestrator.input,
            snapshot=snapshot_payload,
            status=status_payload,
            on_connect=lambda: [
                ("spectator.link", spectator.link()),
                *orchestrator.connection_events(),
            ],
        )

    return app


app = create_app()
