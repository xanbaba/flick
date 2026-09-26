"""tests/test_inputs.py — the keyboard adapter's selection contract.

Asserts inputs/keyboard.py emits exactly one Selection per trial_id,
drops selections for stale trial_ids, and reports its badge, per
ARCHITECTURE.md section 7.1-7.2.
"""

from __future__ import annotations

import asyncio

import pytest

from inputs.keyboard import KeyboardInput


def test_keyboard_reports_its_badge_and_name() -> None:
    keyboard = KeyboardInput()
    assert keyboard.badge == "KEYBOARD INPUT"
    assert keyboard.name == "keyboard"
    assert keyboard.n_targets == 5


async def test_keyboard_emits_a_selection_for_the_current_trial() -> None:
    keyboard = KeyboardInput()
    await keyboard.start()
    await keyboard.set_targets("trial-1", ["a", "b", "c", "d", "Cancel"], "intent")

    keyboard.on_keypress("trial-1", 3)

    selection = await anext(keyboard.selections())
    assert selection.type == "input.selection"
    assert selection.trial_id == "trial-1"
    assert selection.target_idx == 2  # key 3 -> zero-based target index 2
    assert selection.confidence == 1.0
    assert selection.source == "keyboard"
    assert selection.algorithm is None


async def test_keyboard_emits_exactly_one_selection_per_trial_id() -> None:
    keyboard = KeyboardInput()
    await keyboard.start()
    await keyboard.set_targets("trial-2", ["a", "b", "c", "d", "Cancel"], "intent")

    keyboard.on_keypress("trial-2", 1)  # accepted: first keypress for trial-2
    keyboard.on_keypress("trial-2", 4)  # dropped: trial already cleared

    selections = keyboard.selections()
    first = await anext(selections)
    assert first.target_idx == 0

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(selections), timeout=0.05)


async def test_keyboard_drops_a_selection_for_a_stale_trial_id() -> None:
    keyboard = KeyboardInput()
    await keyboard.start()
    await keyboard.set_targets("trial-current", ["a", "b", "c", "d", "Cancel"], "intent")

    keyboard.on_keypress("trial-stale", 2)  # does not match the current trial

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(keyboard.selections()), timeout=0.05)


async def test_keyboard_drops_a_keypress_with_no_active_trial() -> None:
    keyboard = KeyboardInput()
    await keyboard.start()
    # set_targets was never called: there is no current trial_id.

    keyboard.on_keypress("trial-1", 1)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(keyboard.selections()), timeout=0.05)


async def test_keyboard_drops_a_key_out_of_range() -> None:
    keyboard = KeyboardInput()
    await keyboard.start()
    await keyboard.set_targets("trial-1", ["a", "b", "c", "d", "Cancel"], "intent")

    keyboard.on_keypress("trial-1", 9)  # only 1..n_targets are valid

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
