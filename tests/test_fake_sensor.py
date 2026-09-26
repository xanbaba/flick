"""tests/test_fake_sensor.py — the simulated decision state machine.

Asserts scripts/fake_sensor.py's DwellTracker fires exactly once per
completed dwell (section 8.5) and that the resulting bci.selection it
builds is real enough for inputs/ssvep.py to consume end to end over
real ZMQ sockets, with no hardware in the loop.
"""

from __future__ import annotations

import asyncio
import time

import numpy as np
import pytest

from inputs.ssvep import SsvepInput
from scripts.fake_sensor import DwellTracker, TrialTracker, build_sensor_selection
from shared.bus import Publisher
from shared.schemas import ShowTargets

RHO_THRESHOLD = 0.35
MARGIN_RATIO = 1.15
DWELL_WINDOWS = 3


def test_dwell_tracker_fires_after_dwell_windows_then_resets() -> None:
    tracker = DwellTracker(RHO_THRESHOLD, MARGIN_RATIO, DWELL_WINDOWS)
    strong_rho = np.array([0.05, 0.6, 0.05, 0.05, 0.05])  # target 1 clearly wins

    results = [tracker.update(strong_rho) for _ in range(DWELL_WINDOWS)]
    winner_idxs = [r[0] for r in results]
    above_thresholds = [r[2] for r in results]
    dwell_counts = [r[3] for r in results]
    fired_flags = [r[4] for r in results]

    assert winner_idxs == [1, 1, 1]
    assert above_thresholds == [True, True, True]
    assert dwell_counts == [1, 2, 0]  # resets to 0 on the tick it fires
    assert fired_flags == [False, False, True]

    # After firing, the state machine is back at the start: a fresh
    # window needs dwell_windows more ticks before firing again.
    winner_idx, _margin, above_threshold, dwell_count, fired = tracker.update(strong_rho)
    assert dwell_count == 1
    assert fired is False


def test_dwell_tracker_never_fires_when_idle() -> None:
    tracker = DwellTracker(RHO_THRESHOLD, MARGIN_RATIO, DWELL_WINDOWS)
    idle_rho = np.array([0.1, 0.15, 0.12, 0.08, 0.11])  # nothing above threshold

    for _ in range(20):
        *_rest, fired = tracker.update(idle_rho)
        assert fired is False


def test_build_sensor_selection_carries_the_winning_rho() -> None:
    rho = np.array([0.1, 0.72, 0.2, 0.1, 0.1])
    selection = build_sensor_selection("trial-1", winner_idx=1, rho=rho, margin=2.4, ts=123.0)

    assert selection.type == "bci.selection"
    assert selection.trial_id == "trial-1"
    assert selection.target_idx == 1
    assert selection.rho == pytest.approx(0.72)
    assert selection.margin == pytest.approx(2.4)
    assert selection.algorithm == "fbcca"


async def test_trial_tracker_learns_trial_id_from_show_targets() -> None:
    address = "tcp://127.0.0.1:25701"
    publisher = Publisher(address)
    tracker = TrialTracker(address)
    await asyncio.sleep(0.3)  # let the SUB socket's connection settle

    publisher.send(
        ShowTargets(
            type="stim.show_targets",
            ts=time.time(),
            trial_id="trial-42",
            labels=["a", "b", "c", "d", "Cancel"],
            round="intent",
            cue_idx=None,
        )
    )
    await asyncio.sleep(0.2)
    tracker.poll()

    assert tracker.current_trial_id == "trial-42"
    tracker.clear()
    assert tracker.current_trial_id is None

    tracker.close()
    publisher.close()


async def test_ssvep_input_consumes_a_fake_sensor_selection_end_to_end() -> None:
    """This is what "testable before any hardware exists" means:

    a real SensorSelection, built the same way fake_sensor.py builds
    one on dwell completion, flows over a real ZMQ socket into a real
    SsvepInput and comes out the other side as a generic Selection
    with rho mapped to confidence and source set to "ssvep".
    """
    sensor_address = "tcp://127.0.0.1:25702"
    stim_address = "tcp://127.0.0.1:25703"

    sensor_publisher = Publisher(sensor_address)
    ssvep = SsvepInput(sensor_address=sensor_address, stimulus_address=stim_address)
    await ssvep.start()
    await asyncio.sleep(0.3)

    await ssvep.set_targets("trial-9", ["a", "b", "c", "d", "Cancel"], "intent")
    await asyncio.sleep(0.2)

    rho = np.array([0.08, 0.11, 0.09, 0.58, 0.07])
    sensor_selection = build_sensor_selection(
        "trial-9", winner_idx=3, rho=rho, margin=3.1, ts=time.time()
    )
    sensor_publisher.send(sensor_selection)

    selection = await asyncio.wait_for(anext(ssvep.selections()), timeout=2.0)
    assert selection.type == "input.selection"
    assert selection.trial_id == "trial-9"
    assert selection.target_idx == 3
    assert selection.confidence == pytest.approx(0.58)
    assert selection.source == "ssvep"
    assert selection.algorithm == "fbcca"

    await ssvep.stop()
    sensor_publisher.close()
