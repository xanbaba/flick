"""Conversation FSM transitions, driven by the keyboard adapter.

ARCHITECTURE.md section 13: a selection outside a wait state is
dropped, a stale trial_id is dropped, cancel and the 30 s wait
timeout both return to a defined state, and a pair of in-range key
presses completes a turn through SPEAKING.
"""

from __future__ import annotations

import asyncio
import base64
import time
from unittest.mock import AsyncMock

import pytest

from backend.app.orchestrator import (
    CANDIDATE_WAIT,
    IDLE,
    INTENT_WAIT,
    LEARNING,
    SPEAKING,
    UNSEEDED,
    Orchestrator,
)
from backend.app.services.cost import CostTracker
from backend.app.services.speech import SpeechService
from backend.app.services.voice import SpokenResult, VoiceService
from inputs.keyboard import KeyboardInput
from shared.config import get_settings
from shared.schemas import KeyPress


def _press(keyboard: KeyboardInput, key: str) -> None:
    keyboard.handle_key_press(KeyPress(type="client.key_press", ts=time.time(), key=key))


async def _harness(
    tmp_path: object, *, wait_timeout_s: float = 2.0
) -> tuple[Orchestrator, KeyboardInput, list[tuple[str, dict[str, object]]]]:
    events: list[tuple[str, dict[str, object]]] = []

    async def broadcast(message_type: str, payload: dict[str, object]) -> None:
        events.append((message_type, payload))

    keyboard = KeyboardInput(n_targets=5)
    speech = SpeechService(lambda _transcript: None)
    config = get_settings().config
    voice = VoiceService(str(tmp_path), cache_first=False)
    orch = Orchestrator(
        input_source=keyboard,
        broadcast=broadcast,
        voice=voice,
        speech=speech,
        cost=CostTracker(config.privacy.price_table),
        config=config,
        wait_timeout_s=wait_timeout_s,
        stim_address=None,
    )
    await orch.start()
    return orch, keyboard, events


async def test_unseeded_ignores_an_utterance(tmp_path) -> None:
    orch, _keyboard, _events = await _harness(tmp_path)
    try:
        assert orch.state == UNSEEDED
        await orch.submit_utterance("hello there")
        assert orch.state == UNSEEDED
    finally:
        await orch.stop()


@pytest.mark.parametrize("audio", [b"\x00\xfftest audio", b""])
async def test_spoken_event_delivers_audio_when_available(tmp_path, audio: bytes) -> None:
    orch, _keyboard, events = await _harness(tmp_path)
    orch.voice.speak = AsyncMock(
        return_value=SpokenResult(
            text="Hello",
            audio=audio,
            voice="elevenlabs" if audio else "browser",
            cached=False,
            latency_ms=1.0,
        )
    )
    try:
        await orch._speak_and_learn("Hello", [])
        payload = next(payload for kind, payload in events if kind == "conv.spoken")
        assert payload["text"] == "Hello"
        if audio:
            assert base64.b64decode(payload["audio_b64"], validate=True) == audio
        else:
            assert "audio_b64" not in payload
    finally:
        await orch.stop()


async def test_keyboard_presses_complete_a_turn(tmp_path) -> None:
    orch, keyboard, events = await _harness(tmp_path)
    try:
        await orch.seed("bio", "Marcus")
        assert orch.state == IDLE

        async def press_when_waiting() -> None:
            for _ in range(50):
                if orch.state == INTENT_WAIT:
                    break
                await asyncio.sleep(0.02)
            _press(keyboard, "1")
            for _ in range(50):
                if orch.state == CANDIDATE_WAIT:
                    break
                await asyncio.sleep(0.02)
            _press(keyboard, "2")

        await asyncio.gather(orch.submit_utterance("how are you today"), press_when_waiting())
        assert orch.state == IDLE
        states = [payload["state"] for kind, payload in events if kind == "fsm.state"]
        assert INTENT_WAIT in states
        assert CANDIDATE_WAIT in states
        assert SPEAKING in states
        assert LEARNING in states
        spoken = [payload for kind, payload in events if kind == "conv.spoken"]
        assert spoken
        assert spoken[-1]["voice"] == "browser"
        assert spoken[-1]["text"]
    finally:
        await orch.stop()


async def test_selection_outside_wait_is_dropped(tmp_path) -> None:
    orch, keyboard, events = await _harness(tmp_path)
    try:
        await orch.seed("bio", "Marcus")
        _press(keyboard, "1")
        await asyncio.sleep(0.05)
        kinds = [kind for kind, _payload in events]
        assert "input.selection" not in kinds
        assert orch.state == IDLE
    finally:
        await orch.stop()


async def test_stale_trial_key_does_not_advance_the_turn(tmp_path) -> None:
    orch, keyboard, _events = await _harness(tmp_path, wait_timeout_s=0.2)
    try:
        await orch.seed("bio", "Marcus")

        async def press_stale() -> None:
            for _ in range(50):
                if orch.state == INTENT_WAIT:
                    break
                await asyncio.sleep(0.02)
            keyboard._current_trial_id = "not-the-current-trial"
            _press(keyboard, "1")

        await asyncio.gather(orch.submit_utterance("how are you today"), press_stale())
        assert orch.state == IDLE
        assert not hasattr(orch, "last_spoken_text")
    finally:
        await orch.stop()


async def test_wait_timeout_returns_to_idle(tmp_path) -> None:
    orch, _keyboard, events = await _harness(tmp_path, wait_timeout_s=0.05)
    try:
        await orch.seed("bio", "Marcus")
        await orch.submit_utterance("how are you today")
        assert orch.state == IDLE
        details = [payload["detail"] for kind, payload in events if kind == "fsm.state"]
        assert any("No selection" in str(detail) for detail in details)
    finally:
        await orch.stop()


async def test_cancel_on_intents_returns_to_idle(tmp_path) -> None:
    orch, keyboard, events = await _harness(tmp_path)
    try:
        await orch.seed("bio", "Marcus")

        async def cancel() -> None:
            for _ in range(50):
                if orch.state == INTENT_WAIT:
                    break
                await asyncio.sleep(0.02)
            _press(keyboard, "5")

        await asyncio.gather(orch.submit_utterance("how are you today"), cancel())
        assert orch.state == IDLE
        details = [payload["detail"] for kind, payload in events if kind == "fsm.state"]
        assert "cancelled" in details
        assert not any(kind == "conv.spoken" for kind, _payload in events)
    finally:
        await orch.stop()


def test_out_of_range_key_is_dropped_by_the_adapter() -> None:
    keyboard = KeyboardInput(n_targets=5)
    keyboard._current_trial_id = "trial-1"
    keyboard.handle_key_press(KeyPress(type="client.key_press", ts=time.time(), key="9"))
    assert keyboard._queue.empty()


@pytest.mark.parametrize("key", ["1", "2", "3", "4", "5"])
async def test_each_configured_key_maps_onto_a_target(key: str) -> None:
    keyboard = KeyboardInput(n_targets=5)
    await keyboard.set_targets("trial-1", ["a", "b", "c", "d", "Cancel"], "intent")
    keyboard.handle_key_press(KeyPress(type="client.key_press", ts=time.time(), key=key))
    selection = await asyncio.wait_for(anext(keyboard.selections()), timeout=0.2)
    assert selection.target_idx == int(key) - 1
    assert selection.trial_id == "trial-1"
