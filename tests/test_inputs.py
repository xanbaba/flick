"""tests/test_inputs.py — the keyboard adapter's selection contract.

Asserts inputs/keyboard.py consumes a client.key_press message
(ARCHITECTURE.md section 6.3) and emits exactly one Selection per
trial_id, drops presses for a stale or absent trial_id, drops an
out-of-range or non-numeric key, and reports its badge, per section
7.1-7.2.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from inputs.keyboard import KeyboardInput
from shared.schemas import KeyPress


def _key_press(key: str) -> KeyPress:
    return KeyPress(type="client.key_press", ts=time.time(), key=key)


def test_keyboard_reports_its_badge_and_name() -> None:
    keyboard = KeyboardInput()
    assert keyboard.badge == "KEYBOARD INPUT"
    assert keyboard.name == "keyboard"
    assert keyboard.n_targets == 5


async def test_keyboard_emits_a_selection_for_the_current_trial() -> None:
    keyboard = KeyboardInput()
    await keyboard.start()
    await keyboard.set_targets("trial-1", ["a", "b", "c", "d", "Cancel"], "intent")

    keyboard.handle_key_press(_key_press("3"))

    selection = await anext(keyboard.selections())
    assert selection.type == "input.selection"
    assert selection.trial_id == "trial-1"
    assert selection.target_idx == 2  # key "3" -> zero-based target index 2
    assert selection.confidence == 1.0
    assert selection.source == "keyboard"
    assert selection.algorithm is None


async def test_keyboard_accepts_a_raw_dict_payload() -> None:
    """The backend's WS layer hands over parsed JSON, not a model instance."""
    keyboard = KeyboardInput()
    await keyboard.start()
    await keyboard.set_targets("trial-1", ["a", "b", "c", "d", "Cancel"], "intent")

    keyboard.handle_key_press({"type": "client.key_press", "ts": time.time(), "key": "1"})

    selection = await anext(keyboard.selections())
    assert selection.target_idx == 0


async def test_keyboard_emits_exactly_one_selection_per_trial_id() -> None:
    keyboard = KeyboardInput()
    await keyboard.start()
    await keyboard.set_targets("trial-2", ["a", "b", "c", "d", "Cancel"], "intent")

    keyboard.handle_key_press(_key_press("1"))  # accepted: first press for trial-2
    keyboard.handle_key_press(_key_press("4"))  # dropped: trial already cleared

    selections = keyboard.selections()
    first = await anext(selections)
    assert first.target_idx == 0

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(selections), timeout=0.05)


async def test_keyboard_drops_a_key_press_with_no_active_trial() -> None:
    keyboard = KeyboardInput()
    await keyboard.start()
    # set_targets was never called: there is no current trial_id, so
    # this press is stale with nothing to attach it to.

    keyboard.handle_key_press(_key_press("1"))

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(keyboard.selections()), timeout=0.05)


async def test_keyboard_drops_a_key_out_of_range() -> None:
    keyboard = KeyboardInput()
    await keyboard.start()
    await keyboard.set_targets("trial-1", ["a", "b", "c", "d", "Cancel"], "intent")

    keyboard.handle_key_press(_key_press("9"))  # only 1..n_targets are valid

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(keyboard.selections()), timeout=0.05)


async def test_keyboard_drops_a_non_numeric_key() -> None:
    keyboard = KeyboardInput()
    await keyboard.start()
    await keyboard.set_targets("trial-1", ["a", "b", "c", "d", "Cancel"], "intent")

    keyboard.handle_key_press(_key_press("a"))

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(keyboard.selections()), timeout=0.05)


async def test_keyboard_drops_an_invalid_message_without_raising() -> None:
    keyboard = KeyboardInput()
    await keyboard.start()
    await keyboard.set_targets("trial-1", ["a", "b", "c", "d", "Cancel"], "intent")

    # Missing the required "key" field entirely -- fails KeyPress
    # validation. Must be logged and dropped, never raised.
    keyboard.handle_key_press({"type": "client.key_press", "ts": time.time()})

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(keyboard.selections()), timeout=0.05)


async def test_keyboard_status_reflects_start_and_active_trial() -> None:
    keyboard = KeyboardInput()
    await keyboard.start()
    assert keyboard.status() == {"started": True, "current_trial_id": None}

    await keyboard.set_targets("trial-1", ["a", "b", "c", "d", "Cancel"], "intent")
    assert keyboard.status()["current_trial_id"] == "trial-1"

    await keyboard.stop()
    assert keyboard.status() == {"started": False, "current_trial_id": None}
