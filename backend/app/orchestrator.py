"""Conversation FSM (ARCHITECTURE.md section 13).

One instance, one turn task. Every transition broadcasts fsm.state.
INTENT_WAIT and CANDIDATE_WAIT expire after wait_timeout_s (30 s in
production) and return to IDLE. Generation calls expire at
generation.timeout_s and fall through to a correctly-shaped local
placeholder -- the same outcome as the static LLM link, so a turn
still completes with an empty .env and no knowledge-layer services
injected.

Selections arriving outside a *_WAIT state are dropped, and every
show_targets is stamped with a fresh trial_id. A selection whose
trial_id does not match the current one is discarded.
"""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from collections.abc import Awaitable, Callable

from backend.app.services.cost import CostTracker
from backend.app.services.generation import CandidateResult, GenerationService, IntentResult
from backend.app.services.graph import EdgeRef, GraphService
from backend.app.services.interfaces import (
    ExtractionServiceProtocol,
    GenerationServiceProtocol,
    OnboardingServiceProtocol,
    PartnerServiceProtocol,
    RetrievalServiceProtocol,
    SpellerServiceProtocol,
)
from backend.app.services.speech import SpeechService
from backend.app.services.voice import VoiceService
from backend.app.services.worker import MemoryWorker, run_memory
from backend.providers.base import Transcript
from inputs.base import InputSource
from inputs.scan import ScanInput
from shared.bus import Publisher
from shared.config import AppConfig
from shared.logging import get_logger
from shared.schemas import Selection, ShowTargets

logger = get_logger(__name__)

UNSEEDED = "UNSEEDED"
IDLE = "IDLE"
TRANSCRIBING = "TRANSCRIBING"
GROUNDING = "GROUNDING"
INTENT_GEN = "INTENT_GEN"
INTENT_WAIT = "INTENT_WAIT"
CANDIDATE_GEN = "CANDIDATE_GEN"
CANDIDATE_WAIT = "CANDIDATE_WAIT"
SPEAKING = "SPEAKING"
LEARNING = "LEARNING"
SPELLER_WAIT = "SPELLER_WAIT"

_WAIT_STATES = {INTENT_WAIT, CANDIDATE_WAIT, SPELLER_WAIT}
_FALLBACK_LABELS = ["Yes", "No", "Tell me more", "Not now"]
NO_SELECTION_MESSAGE = "No selection — listening again"

Broadcast = Callable[[str, dict[str, object]], Awaitable[None]]


class SeedConflictError(RuntimeError):
    """A persona is already seeded or another seed request is running."""


class Orchestrator:
    def __init__(
        self,
        *,
        input_source: InputSource,
        broadcast: Broadcast,
        voice: VoiceService,
        speech: SpeechService,
        cost: CostTracker,
        config: AppConfig,
        retrieval: RetrievalServiceProtocol | None = None,
        generation: GenerationServiceProtocol | None = None,
        extraction: ExtractionServiceProtocol | None = None,
        partner: PartnerServiceProtocol | None = None,
        onboarding: OnboardingServiceProtocol | None = None,
        speller: SpellerServiceProtocol | None = None,
        wait_timeout_s: float = 30.0,
        stim_address: str | None = None,
        graph: GraphService | None = None,
        worker: MemoryWorker | None = None,
        playback: Callable[[dict[str, object], float], Awaitable[str]] | None = None,
    ) -> None:
        self.graph = graph
        self.worker = worker
        self._playback = playback
        self._playback_unconfirmed = False
        self.input = input_source
        self._broadcast = broadcast
        self.voice = voice
        self.speech = speech
        self.cost = cost
        self.config = config
        self.retrieval = retrieval
        self.generation = generation
        self.extraction = extraction
        self.partner = partner
        self.onboarding = onboarding
        self.speller = speller
        self.wait_timeout_s = wait_timeout_s
        self._stim_address = stim_address

        self.state = UNSEEDED
        self.trial_id: str | None = None
        self.mode = "intent"
        self._labels: list[str] = []
        self._round = "intent"
        self._generation_metadata: dict[str, dict[str, object]] = {}
        self._utterance = ""
        self._intent = ""
        self._turn_id = ""
        self._selection_future: asyncio.Future[Selection | None] | None = None
        self._selection_task: asyncio.Task[None] | None = None
        self._scan_task: asyncio.Task[None] | None = None
        self._grounding_ids: list[str] = []
        self._turn_lock = asyncio.Lock()
        self._stim: Publisher | None = None
        self._seeded = False
        self._user_name = ""
        self._context_node_ids: list[str] = []
        self._context_edges: list[EdgeRef] = []
        self._partner_id: str | None = None
        self._seed_lock = asyncio.Lock()

    async def start(self) -> None:
        await self._start_input()
        await self.speech.start()
        self.speech.gate(True)
        status = await self.onboarding_status()
        if status["seeded"]:
            await self._transition(IDLE, "graph already seeded")
            self.speech.gate(False)
        else:
            await self._transition(UNSEEDED, "awaiting onboarding")

    async def _start_input(self) -> None:
        await self.input.start()
        if self.input.name == "keyboard" and self._stim_address is not None:
            self._stim = Publisher(self._stim_address)
        self._selection_task = asyncio.create_task(self._selection_loop())
        if isinstance(self.input, ScanInput):
            self._scan_task = asyncio.create_task(self._scan_loop(self.input))

    async def _scan_loop(self, source: ScanInput) -> None:
        async for kind, payload in source.events():
            # Keep the legacy five-tile UI stable until its frontend migration.
            if source.n_targets == 4:
                await self._broadcast(kind, payload)
            if (
                kind == "scan.idle"
                and payload.get("reason") in ("timeout", "sensor_transport_error", "input_overflow")
                and payload.get("trial_id") == self.trial_id
            ):
                future = self._selection_future
                if future is not None and not future.done():
                    future.set_result(None)

    async def _stop_input(self) -> None:
        if self._scan_task is not None:
            self._scan_task.cancel()
            await asyncio.gather(self._scan_task, return_exceptions=True)
            self._scan_task = None
        if self._selection_task is not None:
            self._selection_task.cancel()
            await asyncio.gather(self._selection_task, return_exceptions=True)
            self._selection_task = None
        await self.input.stop()
        if self._stim is not None:
            self._stim.close()
            self._stim = None

    async def swap_input(self, replacement: InputSource) -> None:
        """Transfer the selection listener and stimulus socket, rolling back on failure."""
        if self.state not in (IDLE, UNSEEDED) or self._turn_lock.locked():
            raise ValueError("Cannot switch input during a conversation turn")
        async with self._turn_lock:
            previous = self.input
            await self._stop_input()
            self.input = replacement
            try:
                await self._start_input()
            except Exception:
                await self._stop_input()
                self.input = previous
                await self._start_input()
                raise

    async def stop(self) -> None:
        await self._stop_input()
        await self.speech.stop()

    async def seed(self, bio: str, name: str) -> dict[str, object]:
        if self._seed_lock.locked():
            raise SeedConflictError("Biography seeding is already in progress")
        async with self._seed_lock:
            if (await self.onboarding_status())["seeded"]:
                raise SeedConflictError("A persona already exists; reseeding is not supported")
            try:
                if self.onboarding is not None:
                    async for batch in self.onboarding.seed(bio, name):
                        await self._broadcast("graph.bloom", batch.model_dump())
                else:
                    # Standalone orchestration tests may omit the knowledge layer.
                    self._seeded = True
                    self._user_name = name
            finally:
                status = await self.onboarding_status()
                if status["seeded"]:
                    await self._transition(IDLE, f"seeded as {self._user_name}")
                    self.speech.gate(False)
            return status

    async def onboarding_status(self) -> dict[str, object]:
        if self.graph is None:
            return {"seeded": self._seeded, "node_count": 0}
        people = await run_memory(self.worker, self.graph.people)
        user = next((person for person in people if person.id == "user"), None)
        self._seeded = user is not None
        self._user_name = user.name if user is not None else ""
        return {
            "seeded": self._seeded,
            "node_count": await run_memory(self.worker, self.graph.node_count),
        }

    async def snapshot(self) -> dict[str, object]:
        if self.graph is None:
            return {"nodes": [], "edges": []}
        nodes, edges = await run_memory(self.worker, self.graph.snapshot)
        return {
            "nodes": [node.model_dump() for node in nodes],
            "edges": [edge.model_dump() for edge in edges],
        }

    def connection_events(self) -> list[tuple[str, dict[str, object]]]:
        """Restore the current choices without starting a new selection trial."""
        events: list[tuple[str, dict[str, object]]] = []
        if self.state == INTENT_WAIT:
            events.append(
                (
                    "conv.intents",
                    {
                        "trial_id": self.trial_id,
                        "labels": self._labels,
                        **self._generation_metadata.get("intent", {}),
                    },
                )
            )
        elif self.state == CANDIDATE_WAIT:
            events.append(
                (
                    "conv.candidates",
                    {
                        "trial_id": self.trial_id,
                        "candidates": self._labels,
                        "grounding": self._grounding_ids,
                        **self._generation_metadata.get("candidate", {}),
                    },
                )
            )
        if isinstance(self.input, ScanInput) and self.input.n_targets == 4:
            if self.input.scan.active():
                events.append(("scan.targets", self.input.scan.snapshot()))
            else:
                events.append(("scan.idle", {"trial_id": self.trial_id, "reason": "inactive"}))
        events.append(("fsm.state", {"state": self.state, "detail": "connected"}))
        return events

    async def submit_utterance(self, text: str) -> None:
        """Run a turn until it is waiting on a selection, or has returned to IDLE."""
        if self.state != IDLE:
            logger.info("orchestrator.utterance_dropped", state=self.state)
            return
        async with self._turn_lock:
            if self.state != IDLE:
                return
            await self._run_until_waiting(text)

    async def _selection_loop(self) -> None:
        async for selection in self.input.selections():
            await self._on_selection(selection)

    async def _on_selection(self, selection: Selection) -> None:
        if self.state not in _WAIT_STATES:
            logger.debug("orchestrator.selection_outside_wait", state=self.state)
            return
        if selection.trial_id != self.trial_id:
            logger.debug(
                "orchestrator.stale_selection_dropped",
                trial_id=selection.trial_id,
                current=self.trial_id,
            )
            return
        label = ""
        if 0 <= selection.target_idx < len(self._labels):
            label = self._labels[selection.target_idx]
        if not label.strip():
            logger.debug("orchestrator.inactive_target_dropped", target_idx=selection.target_idx)
            return
        await self._broadcast(
            "input.selection",
            {
                "target_idx": selection.target_idx,
                "label": label,
                "round": self._round,
                "confidence": selection.confidence,
                "source": selection.source,
            },
        )
        future = self._selection_future
        if future is not None and not future.done():
            future.set_result(selection)

    async def _run_until_waiting(self, text: str) -> None:
        self._turn_id = uuid.uuid4().hex
        self._utterance = text
        cost_turn = self.cost.start_turn(self._turn_id)
        try:
            await self._transition(TRANSCRIBING, text)
            await self._ground()
            await self._broadcast(
                "conv.transcript",
                {
                    "speaker": "partner",
                    "text": text,
                    "partner_id": self._partner_id,
                    "partner_name": self._partner_name if self._partner_id else None,
                    "confidence": 1.0,
                },
            )
            if self.mode == "speller" and self.speller is not None:
                await self._speller_loop()
                return
            await self._intent_round()
        finally:
            summary = cost_turn.finalize()
            await self._broadcast("privacy.cost", summary.model_dump())

    async def _ground(self) -> None:
        await self._transition(GROUNDING, "partner id + retrieval")
        self._partner_name = "someone"
        self._partner_relationship = "unknown"
        self._partner_id = None
        if self.partner is not None:
            identified = await self.partner.identify(self._utterance)
            self._partner_id = identified.partner_id
            if self.graph is not None:
                people = await run_memory(self.worker, self.graph.people)
                current = next((p for p in people if p.id == self._partner_id), None)
                if current is not None:
                    self._partner_name = current.name
                    self._partner_relationship = current.relationship
        await self._retrieve(self._utterance)

    async def _retrieve(self, query: str) -> None:
        self._context = ""
        self._context_node_ids = []
        self._context_edges = []
        if self.retrieval is None:
            return
        result = await run_memory(
            self.worker, self.retrieval.retrieve, query, partner_id=self._partner_id
        )
        self._context = result.context_text
        self._context_node_ids = [node.id for node in result.nodes if node.fact]
        self._context_edges = result.edges
        if result.activated_node_ids:
            await self._broadcast(
                "graph.activate",
                {
                    "node_ids": result.activated_node_ids,
                    "edge_ids": [edge.id for edge in result.edges],
                    "reason": "retrieval",
                },
            )

    async def _intent_round(self) -> None:
        await self._transition(INTENT_GEN, "generating intent labels")
        labels = await self._intent_labels()
        self._labels = labels
        while True:
            selection = await self._show_and_wait(labels, "intent", INTENT_WAIT)
            if selection is None or self._is_cancel(selection):
                await self._idle(NO_SELECTION_MESSAGE if selection is None else "cancelled")
                return
            self._intent = labels[selection.target_idx]
            await self._transition(CANDIDATE_GEN, self._intent)
            await self._retrieve(f"{self._utterance}\nChosen intent: {self._intent}")
            candidates, grounding = await self._candidates()
            selection = await self._show_and_wait(
                candidates, "candidate", CANDIDATE_WAIT, grounding
            )
            if selection is None:
                await self._idle(NO_SELECTION_MESSAGE)
                return
            if self._is_cancel(selection):
                await self._transition(INTENT_WAIT, "cancelled candidates, same labels")
                continue
            spoken = candidates[selection.target_idx]
            await self._speak_and_learn(spoken, grounding)
            return

    async def _show_and_wait(
        self,
        labels: list[str],
        round_name: str,
        wait_state: str,
        grounding: list[str] | None = None,
    ) -> Selection | None:
        self.trial_id = uuid.uuid4().hex
        self._labels = labels
        self._round = round_name
        self._grounding_ids = grounding or []
        loop = asyncio.get_running_loop()
        self._selection_future = loop.create_future()
        await self.input.set_targets(self.trial_id, labels, round_name)
        self._publish_show_targets(labels, round_name)
        event = "conv.intents" if round_name == "intent" else "conv.candidates"
        payload: dict[str, object] = {"trial_id": self.trial_id, "labels": labels}
        if round_name != "intent":
            payload = {
                "trial_id": self.trial_id,
                "candidates": labels,
                "grounding": grounding or [],
            }
        payload.update(self._generation_metadata.get(round_name, {}))
        await self._broadcast(event, payload)
        await self._transition(wait_state, self.trial_id)
        try:
            return await asyncio.wait_for(self._selection_future, self.wait_timeout_s)
        except TimeoutError:
            return None
        finally:
            self.input.close_trial("round_closed")

    def _publish_show_targets(self, labels: list[str], round_name: str) -> None:
        if self._stim is None or self.trial_id is None:
            return
        if round_name not in ("intent", "candidate", "speller"):
            return
        self._stim.send(
            ShowTargets(
                type="stim.show_targets",
                ts=time.time(),
                trial_id=self.trial_id,
                labels=labels,
                round=round_name,  # type: ignore[arg-type]
                cue_idx=None,
            )
        )

    def _is_cancel(self, selection: Selection) -> bool:
        return selection.target_idx == len(self._labels) - 1 and self._labels[-1] == "Cancel"

    async def _speak_and_learn(self, text: str, grounding: list[str]) -> None:
        await self._transition(SPEAKING, text)
        self.speech.gate(True)
        try:
            spoken = await self.voice.speak(text)
        except Exception as exc:
            logger.warning("orchestrator.speech_failed", error_type=type(exc).__name__)
            await self._idle("Speech unavailable; please try again")
            return
        payload: dict[str, object] = {
            "text": spoken.text,
            "voice": spoken.voice,
            "cached": spoken.cached,
            "latency_ms": spoken.latency_ms,
        }
        if spoken.audio:
            payload["audio_b64"] = base64.b64encode(spoken.audio).decode("ascii")
        outcome = "completed"
        if self._playback is None:
            await self._broadcast("conv.spoken", payload)
        else:
            try:
                outcome = await self._playback(payload, self.wait_timeout_s)
            except Exception as exc:
                logger.warning("orchestrator.playback_failed", error_type=type(exc).__name__)
                outcome = "unconfirmed"
        if outcome == "unconfirmed":
            self._playback_unconfirmed = True
        self.last_spoken_voice = spoken.voice
        self.last_spoken_text = spoken.text
        await self._transition(LEARNING, "reinforce + extract")
        if grounding:
            await self._broadcast(
                "graph.activate",
                {"node_ids": grounding, "edge_ids": [], "reason": "spoken"},
            )
        detail = "turn complete"
        if outcome != "completed":
            logger.warning("orchestrator.playback_incomplete", outcome=outcome)
            detail += (
                "; playback unconfirmed, microphone muted until backend restart"
                if outcome == "unconfirmed"
                else "; audio playback unavailable"
            )
        try:
            if self.graph is not None:
                grounded = set(grounding) & set(self._context_node_ids)
                edge_ids = [
                    edge.id
                    for edge in self._context_edges
                    if edge.source in grounded and edge.target in grounded
                ]
                await run_memory(
                    self.worker,
                    self.graph.reinforce,
                    list(grounded),
                    edge_ids,
                    node_increment=self.config.reinforcement.node_increment,
                    edge_increment=self.config.reinforcement.edge_increment,
                    max_weight=self.config.reinforcement.max_weight,
                )
            if self.extraction is not None:
                extracted = await self.extraction.extract_and_writeback(self._utterance, text)
                snapshot = await self.snapshot()
                nodes = [n for n in snapshot["nodes"] if n["id"] in extracted.committed_node_ids]
                edges = [e for e in snapshot["edges"] if e["id"] in extracted.committed_edge_ids]
                if nodes or edges:
                    await self._broadcast("graph.bloom", {"nodes": nodes, "edges": edges})
        except Exception as exc:
            logger.warning("orchestrator.learning_failed", error_type=type(exc).__name__)
            detail += "; memory update unavailable"
        finally:
            if self.graph is not None:
                try:
                    await self._broadcast("graph.snapshot", await self.snapshot())
                except Exception as exc:
                    logger.warning("orchestrator.snapshot_failed", error_type=type(exc).__name__)
                    detail += "; memory update unavailable"
            await self._idle(detail, rearm_mic=outcome != "unconfirmed")

    async def _idle(self, detail: str, *, rearm_mic: bool = True) -> None:
        self.input.close_trial("idle")
        self.trial_id = None
        self._selection_future = None
        self.speech.gate(self._playback_unconfirmed or not rearm_mic)
        await self._transition(IDLE, detail)

    async def _intent_labels(self) -> list[str]:
        n_semantic = min(self.config.generation.n_intents, self.input.n_targets - 1)
        try:
            generation = self.generation or GenerationService(config=self.config.generation)
            result = await generation.generate_intent_result(
                self._context, self._partner_name, self._partner_relationship, self._utterance
            )
        except Exception as exc:
            logger.warning("orchestrator.intent_gen_fell_through", error_type=type(exc).__name__)
            result = IntentResult(
                labels=_FALLBACK_LABELS, source="fallback", fallback_reason="provider_error"
            )
        self._generation_metadata["intent"] = {
            "source": result.source,
            "fallback_reason": result.fallback_reason,
        }
        return self._with_cancel(result.labels[:n_semantic])

    def _with_cancel(self, labels: list[str]) -> list[str]:
        """Keep Cancel on the last physical target in every conversation round."""
        available = self.input.n_targets - 1
        semantic = labels[:available]
        return semantic + [""] * (available - len(semantic)) + ["Cancel"]

    async def _candidates(self) -> tuple[list[str], list[str]]:
        try:
            generation = self.generation or GenerationService(config=self.config.generation)
            result = await generation.generate_candidates(
                user_name=self._user_name,
                context=self._context,
                context_node_ids=self._context_node_ids,
                partner_name=self._partner_name,
                partner_relationship=self._partner_relationship,
                utterance=self._utterance,
                intent=self._intent,
            )
        except Exception as exc:
            logger.warning("orchestrator.candidate_gen_fell_through", error_type=type(exc).__name__)
            result = CandidateResult(
                candidates=[self._intent],
                grounding=[],
                source="fallback",
                fallback_reason="provider_error",
            )
        self._generation_metadata["candidate"] = {
            "source": result.source,
            "fallback_reason": result.fallback_reason,
        }
        grounding = [node_id for node_id in result.grounding if node_id in self._context_node_ids]
        return self._with_cancel(
            result.candidates[: self.config.generation.n_candidates]
        ), grounding

    async def _speller_loop(self) -> None:
        assert self.speller is not None
        self.speller.reset()
        path: list[int] = []
        labels = await self.speller.root_labels()
        while True:
            selection = await self._show_and_wait(labels, "speller", SPELLER_WAIT)
            if selection is None or self._is_cancel(selection):
                await self._idle(NO_SELECTION_MESSAGE if selection is None else "cancelled")
                return
            path.append(selection.target_idx)
            nxt = await self.speller.next_labels(path)
            if nxt is None:
                await self._speak_and_learn(self.speller.spelled_text(), [])
                return
            labels = nxt

    async def on_transcript(self, transcript: Transcript) -> None:
        if self.state != IDLE:
            return
        await self.submit_utterance(transcript.text)

    async def _transition(self, state: str, detail: str) -> None:
        self.state = state
        await self._broadcast("fsm.state", {"state": state, "detail": detail})
        logger.info("orchestrator.transition", state=state, detail=detail)
