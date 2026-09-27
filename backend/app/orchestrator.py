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
import json
import time
import uuid
from collections.abc import Awaitable, Callable

from backend.app.services.cost import CostTracker
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
from backend.providers.base import Transcript
from backend.providers.registry import get_llm_provider
from inputs.base import InputSource
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
_FALLBACK_CANDIDATES = [
    "Yes.",
    "I am not sure about that.",
    "Can you say a little more about what you mean?",
]
NO_SELECTION_MESSAGE = "No selection — listening again"

Broadcast = Callable[[str, dict[str, object]], Awaitable[None]]


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
    ) -> None:
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
        self._utterance = ""
        self._intent = ""
        self._turn_id = ""
        self._selection_future: asyncio.Future[Selection] | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._turn_lock = asyncio.Lock()
        self._stim: Publisher | None = None
        self._seeded = False
        self._user_name = ""
        self._context_node_ids: list[str] = []

    async def start(self) -> None:
        await self.input.start()
        await self.speech.start()
        self.speech.gate(True)
        if self._stim_address is not None:
            try:
                self._stim = Publisher(self._stim_address)
            except Exception as exc:
                logger.warning("orchestrator.stim_bind_failed", error=str(exc))
                self._stim = None
        if self.onboarding is not None and self.onboarding.status().get("seeded"):
            self._seeded = True
            await self._transition(IDLE, "graph already seeded")
            self.speech.gate(False)
        else:
            await self._transition(UNSEEDED, "awaiting onboarding")
        self._tasks.append(asyncio.create_task(self._selection_loop()))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.input.stop()
        await self.speech.stop()
        if self._stim is not None:
            self._stim.close()
            self._stim = None

    async def seed(self, bio: str, name: str) -> dict[str, object]:
        if self.onboarding is not None:
            result = await self.onboarding.seed(bio, name)
            payload: dict[str, object] = {
                "seeded": True,
                "node_count": result.node_count,
            }
        else:
            # No onboarding service yet: the turn still has to be able
            # to leave UNSEEDED (acceptance test A6). Nothing is written
            # to a graph that does not exist.
            payload = {"seeded": True, "node_count": 0}
        self._seeded = True
        self._user_name = name
        await self._transition(IDLE, f"seeded as {name}")
        self.speech.gate(False)
        return payload

    def onboarding_status(self) -> dict[str, object]:
        if self.onboarding is not None:
            return dict(self.onboarding.status())
        return {"seeded": self._seeded, "node_count": 0}

    async def submit_utterance(self, text: str) -> None:
        """Run a turn until it is waiting on a selection, or has returned to IDLE."""
        if self.state != IDLE:
            logger.info("orchestrator.utterance_dropped", state=self.state)
            return
        async with self._turn_lock:
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
            await self._broadcast(
                "conv.transcript",
                {
                    "speaker": "partner",
                    "text": text,
                    "partner_id": None,
                    "partner_name": None,
                    "confidence": 1.0,
                },
            )
            await self._ground()
            if self.mode == "speller" and self.speller is not None:
                await self._speller_loop()
                return
            await self._intent_round()
        finally:
            summary = cost_turn.finalize()
            await self._broadcast("privacy.cost", summary.model_dump())

    async def _ground(self) -> None:
        await self._transition(GROUNDING, "partner id + retrieval")
        partner_name = "someone"
        partner_relationship = "unknown"
        partner_id: str | None = None
        if self.partner is not None:
            identified = await self.partner.identify(self._utterance)
            partner_id = identified.partner_id
            current = self.partner.get_current()
            if current is not None:
                partner_name = current.name
                partner_relationship = current.relationship
        context = ""
        self._context_node_ids = []
        activated: list[str] = []
        if self.retrieval is not None:
            result = await self.retrieval.retrieve(
                self._utterance,
                partner_id=partner_id,
                select_k=self.config.retrieval.select_k,
            )
            context = result.context_text
            self._context_node_ids = [node.id for node in result.nodes]
            activated = result.activated_node_ids
        self._context = context
        self._partner_name = partner_name
        self._partner_relationship = partner_relationship
        if activated:
            await self._broadcast(
                "graph.activate",
                {"node_ids": activated, "edge_ids": [], "reason": "grounding"},
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
            candidates, grounding = await self._candidates()
            selection = await self._show_and_wait(candidates, "candidate", CANDIDATE_WAIT)
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
        self, labels: list[str], round_name: str, wait_state: str
    ) -> Selection | None:
        self.trial_id = uuid.uuid4().hex
        self._labels = labels
        self._round = round_name
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
                "grounding": [],
            }
        await self._broadcast(event, payload)
        await self._transition(wait_state, self.trial_id)
        try:
            return await asyncio.wait_for(self._selection_future, self.wait_timeout_s)
        except TimeoutError:
            return None

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
        finally:
            self.speech.gate(False)
        payload: dict[str, object] = {
            "text": spoken.text,
            "voice": spoken.voice,
            "cached": spoken.cached,
            "latency_ms": spoken.latency_ms,
        }
        if spoken.audio:
            payload["audio_b64"] = base64.b64encode(spoken.audio).decode("ascii")
        await self._broadcast("conv.spoken", payload)
        self.last_spoken_voice = spoken.voice
        self.last_spoken_text = spoken.text
        await self._transition(LEARNING, "reinforce + extract")
        if grounding:
            await self._broadcast(
                "graph.activate",
                {"node_ids": grounding, "edge_ids": [], "reason": "spoken"},
            )
        if self.extraction is not None:
            extracted = await self.extraction.extract_and_writeback(self._utterance, text)
            await self._broadcast(
                "graph.bloom",
                {
                    "nodes": [node.model_dump() for node in extracted.nodes],
                    "edges": [edge.model_dump() for edge in extracted.edges],
                },
            )
        await self._idle("turn complete")

    async def _idle(self, detail: str) -> None:
        self.trial_id = None
        self._selection_future = None
        self.speech.gate(False)
        await self._transition(IDLE, detail)

    async def _intent_labels(self) -> list[str]:
        n_semantic = min(self.config.generation.n_intents, self.input.n_targets - 1)
        labels: list[str] = []
        if self.generation is not None:
            try:
                labels = await asyncio.wait_for(
                    self.generation.generate_intents(
                        self._context,
                        self._partner_name,
                        self._partner_relationship,
                        self._utterance,
                    ),
                    timeout=self.config.generation.timeout_s,
                )
            except Exception as exc:
                logger.warning(
                    "orchestrator.intent_gen_fell_through",
                    error=str(exc) or type(exc).__name__,
                    error_type=type(exc).__name__,
                    timeout_s=self.config.generation.timeout_s,
                )
                labels = []
            if len(labels) < n_semantic:
                labels = _FALLBACK_LABELS[:n_semantic]
        if len(labels) < n_semantic:
            labels = await self._offline_json_list("labels", n_semantic, _FALLBACK_LABELS)
        return labels[:n_semantic] + ["Cancel"]

    async def _candidates(self) -> tuple[list[str], list[str]]:
        n = self.config.generation.n_candidates
        if self.generation is not None:
            try:
                result = await asyncio.wait_for(
                    self.generation.generate_candidates(
                        user_name=self._user_name,
                        context=self._context,
                        context_node_ids=self._context_node_ids,
                        partner_name=self._partner_name,
                        partner_relationship=self._partner_relationship,
                        utterance=self._utterance,
                        intent=self._intent,
                    ),
                    timeout=self.config.generation.timeout_s,
                )
                candidates, grounding = result.candidates, result.grounding
            except Exception as exc:
                logger.warning(
                    "orchestrator.candidate_gen_fell_through",
                    error=str(exc) or type(exc).__name__,
                    error_type=type(exc).__name__,
                    timeout_s=self.config.generation.timeout_s,
                )
                candidates, grounding = [], []
            if len(candidates) >= n:
                return candidates[:n] + ["Cancel"], grounding
            return _FALLBACK_CANDIDATES[:n] + ["Cancel"], []
        candidates = await self._offline_json_list("candidates", n, _FALLBACK_CANDIDATES)
        return candidates[:n] + ["Cancel"], []

    async def _offline_json_list(self, key: str, n: int, fallback: list[str]) -> list[str]:
        """Call the LLM chain. The static link returns ``{}``, which is not
        a usable list, so the local placeholder is what actually renders.
        """
        try:
            raw = await asyncio.wait_for(
                get_llm_provider().complete(
                    key,
                    self._utterance,
                    json_mode=True,
                    timeout=self.config.generation.timeout_s,
                ),
                timeout=self.config.generation.timeout_s,
            )
            parsed = json.loads(raw)
            values = parsed.get(key) if isinstance(parsed, dict) else None
            if isinstance(values, list) and len(values) >= n:
                return [str(item) for item in values[:n]]
        except Exception as exc:
            logger.warning(
                "orchestrator.offline_llm_unusable",
                error=str(exc) or type(exc).__name__,
                error_type=type(exc).__name__,
            )
        return fallback[:n]

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
