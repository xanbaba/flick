from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from inputs.keyboard import KeyboardInput
from inputs.scan import ScanController
from shared.config import ScanConfig

LABELS = ["Yes", "No", "Tell me more", "Cancel"]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def controller(**settings: object) -> tuple[ScanController, Clock, list]:
    clock, events = Clock(), []
    scan = ScanController(
        ScanConfig(**settings),
        clock=clock,
        wall_clock=clock,
        emit=lambda kind, payload: events.append((kind, payload)),
    )
    return scan, clock, events


def test_scan_wraps_skips_blanks_and_retains_cancel() -> None:
    scan, _, events = controller(start_idx=1)
    scan.set_targets("one", ["Yes", "", "No", "Cancel"], "candidate")
    assert scan.highlight_idx == 2
    for expected in [3, 0, 2]:
        scan.advance()
        assert scan.highlight_idx == expected
    assert scan.moves == 3
    assert events[0][0] == "scan.targets" and events[-1][0] == "scan.highlight"


def test_selection_closes_immediately_but_delivers_after_hold_once() -> None:
    scan, clock, events = controller(hold_after_select_s=0.6)
    scan.set_targets("one", LABELS, "intent")
    scan.advance()
    scan.select(source="bci", confidence=0.8, trigger_kind="eyes_closed")
    scan.advance()
    scan.select(source="bci")
    assert not scan.active() and scan.tick() is None
    with pytest.raises(RuntimeError):
        scan.set_targets("two", LABELS, "candidate")
    clock.now += 0.61
    selected = scan.tick()
    assert selected.target_idx == 1 and selected.moves == 1
    assert selected.algorithm == "step_scan" and selected.confidence == 0.8
    assert selected.trigger_kind == "eyes_closed"
    assert scan.tick() is None
    assert [kind for kind, _ in events].count("scan.selected") == 1
    scan.set_targets("two", LABELS, "candidate")
    assert scan.moves == 0 and scan.highlight_idx == 0


def test_timeout_and_close_reject_late_picks() -> None:
    scan, clock, events = controller(trial_timeout_s=1)
    scan.set_targets("one", LABELS, "intent")
    clock.now += 1
    scan.select(source="keyboard")
    assert scan.tick() is None and events[-1][1]["reason"] == "timeout"
    scan.set_targets("two", LABELS, "intent")
    scan.select(source="keyboard")
    scan.close("stopped")
    clock.now += 10
    assert scan.tick() is None
    with pytest.raises(ValueError):
        scan.set_targets("one", LABELS, "intent")


@pytest.mark.parametrize(
    "labels", [[], ["Yes", "Cancel"], ["Yes", "No", "", "Back"], ["", "", "", "Cancel"]]
)
def test_invalid_targets_leave_current_trial_intact(labels: list[str]) -> None:
    scan, _, _ = controller()
    scan.set_targets("one", LABELS, "intent")
    with pytest.raises(ValueError):
        scan.set_targets("two", labels, "intent")
    assert scan.trial_id == "one"


def test_direct_pick_rejects_blank_negative_and_out_of_range() -> None:
    scan, _, _ = controller(hold_after_select_s=0)
    scan.set_targets("one", ["Yes", "", "", "Cancel"], "candidate")
    for index in [-1, 1, 2, 4]:
        scan.select(source="keyboard", target_idx=index)
        assert scan.active()
    scan.select(source="keyboard", target_idx=3)
    assert scan.tick().target_idx == 3


@pytest.mark.parametrize(
    "settings",
    [
        dict(trial_timeout_s=0),
        dict(status_max_age_s=-1),
        dict(event_max_age_s=float("inf")),
        dict(hold_after_select_s=-1),
        dict(start_idx=4),
    ],
)
def test_invalid_scan_config_is_rejected(settings: dict) -> None:
    with pytest.raises(ValidationError):
        ScanConfig(**settings)


async def test_keyboard_shares_scan_and_requires_fresh_matching_trial() -> None:
    keyboard = KeyboardInput(4, config=ScanConfig(hold_after_select_s=0))
    clock = Clock()
    keyboard.scan.clock = keyboard.scan.wall_clock = clock
    await keyboard.start()
    try:
        await keyboard.set_targets("one", LABELS, "intent")
        for trial, ts in [(None, clock()), ("old", clock()), ("one", clock() - 1)]:
            keyboard.handle_key_press(dict(type="client.key_press", ts=ts, key="n", trial_id=trial))
        assert keyboard.scan.highlight_idx == 0
        for key in ["n", "n", "s"]:
            keyboard.handle_key_press(
                dict(type="client.key_press", ts=clock(), key=key, trial_id="one")
            )
        selected = await asyncio.wait_for(anext(keyboard.selections()), 0.2)
        assert selected.target_idx == 2 and selected.moves == 2
        assert selected.source == "keyboard" and selected.confidence == 1
        await keyboard.set_targets("two", LABELS, "candidate")
        keyboard.handle_key_press(
            dict(type="client.key_press", ts=clock(), key="s", trial_id="one")
        )
        assert keyboard.scan.active()
    finally:
        await keyboard.stop()


async def test_unstarted_or_stopped_adapter_cannot_open_trial() -> None:
    keyboard = KeyboardInput(4)
    with pytest.raises(RuntimeError):
        await keyboard.set_targets("one", LABELS, "intent")
    await keyboard.start()
    await keyboard.stop()
    with pytest.raises(RuntimeError):
        await keyboard.set_targets("two", LABELS, "intent")
