from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import zmq

from inputs.bci import BciInput
from shared.config import ScanConfig, SensorSettings
from shared.schemas import SensorStatus, TriggerEvent, TriggerLevel

LABELS = ["Yes", "No", "More", "Cancel"]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def ready(ts: float, **fields: object) -> SensorStatus:
    return SensorStatus(
        ts=ts, source="synthetic", connected=True, calibrated=True, armed=True, **fields
    )


def levels(ts: float, value: float = 0) -> TriggerLevel:
    return TriggerLevel(
        ts=ts, next_level=value, next_threshold=8, select_level=value, select_threshold=2
    )


def trigger(ts: float, role: str = "next", **fields: object) -> TriggerEvent:
    return TriggerEvent(
        event_id=str(uuid4()),
        ts=ts,
        source_ts=ts,
        role=role,
        kind="jaw_clench" if role == "next" else "eyes_closed",
        strength=0.9,
        **fields,
    )


@pytest.fixture
async def adapter() -> AsyncIterator[tuple[BciInput, Clock]]:
    clock = Clock()
    bci = BciInput(
        config=ScanConfig(hold_after_select_s=0, coalesce_s=0.03),
        sensor=SensorSettings(source="synthetic", pub_address=f"inproc://{uuid4()}"),
    )
    bci.scan.clock = bci.scan.wall_clock = clock
    await bci.start()
    await bci.set_targets("one", LABELS, "intent")
    bci.handle_message(ready(clock()))
    bci.handle_message(levels(clock()))
    try:
        yield bci, clock
    finally:
        await bci.stop()


def flush(bci: BciInput, clock: Clock) -> None:
    clock.now += 0.04
    bci.tick()


async def test_next_select_produces_one_correlated_selection(adapter: tuple) -> None:
    bci, clock = adapter
    bci.handle_message(trigger(clock()))
    flush(bci, clock)
    assert bci.scan.highlight_idx == 1
    bci.handle_message(trigger(clock(), "select", contaminated=True))
    flush(bci, clock)
    selection = await asyncio.wait_for(anext(bci.selections()), 0.2)
    assert selection.trial_id == "one" and selection.target_idx == 1
    assert selection.source == "bci" and selection.algorithm == "step_scan"
    assert selection.moves == 1 and selection.trigger_kind == "eyes_closed"
    assert selection.confidence == 0.9
    bci.handle_message(trigger(clock(), "select"))
    flush(bci, clock)
    assert bci._queue.empty()


@pytest.mark.parametrize("order", [("next", "select"), ("select", "next")])
async def test_same_sample_select_wins_in_either_arrival_order(
    adapter: tuple, order: tuple
) -> None:
    bci, clock = adapter
    sample = clock()
    bci.handle_message(trigger(sample, order[0]))
    clock.now += 0.01
    bci.handle_message(trigger(sample, order[1]))
    flush(bci, clock)
    selection = await asyncio.wait_for(anext(bci.selections()), 0.2)
    assert selection.target_idx == 0 and selection.moves == 0


@pytest.mark.parametrize(
    "field,delta", [("ts", -2), ("source_ts", -2), ("ts", 1), ("source_ts", 1), ("source_ts", -0.1)]
)
async def test_stale_future_or_pretrial_events_do_not_move(
    adapter: tuple, field: str, delta: float
) -> None:
    bci, clock = adapter
    event = trigger(clock()).model_copy(update={field: clock() + delta})
    bci.handle_message(event)
    flush(bci, clock)
    assert bci.scan.highlight_idx == 0


async def test_duplicate_id_and_repeated_source_sample_are_rejected(adapter: tuple) -> None:
    bci, clock = adapter
    event = trigger(clock())
    bci.handle_message(event)
    flush(bci, clock)
    bci.handle_message(levels(clock()))
    bci.handle_message(event.model_copy(update={"ts": clock(), "source_ts": clock()}))
    bci.handle_message(trigger(event.source_ts))
    flush(bci, clock)
    assert bci.scan.moves == 1


async def test_new_trial_needs_release_and_clears_queued_actions(adapter: tuple) -> None:
    bci, clock = adapter
    bci.handle_message(trigger(clock()))
    clock.now += 0.01
    await bci.set_targets("two", LABELS, "candidate")
    flush(bci, clock)
    bci.handle_message(levels(clock(), 20))
    bci.handle_message(trigger(clock(), "select"))
    flush(bci, clock)
    assert bci.scan.moves == 0 and bci.scan.active()
    bci.handle_message(levels(clock()))
    bci.handle_message(trigger(clock(), "select"))
    flush(bci, clock)
    assert (await anext(bci.selections())).trial_id == "two"


async def test_readiness_expiry_disarms_and_recovery_requires_release(adapter: tuple) -> None:
    bci, clock = adapter
    clock.now += 3
    bci.tick()
    assert not bci.status()["ready"]
    bci.handle_message(trigger(clock()))
    bci.handle_message(ready(clock()))
    clock.now += 0.01
    bci.handle_message(trigger(clock(), "select"))
    flush(bci, clock)
    assert bci.scan.active() and bci.scan.moves == 0
    bci.handle_message(levels(clock()))
    bci.handle_message(trigger(clock(), "select"))
    flush(bci, clock)
    assert (await anext(bci.selections())).target_idx == 0


@pytest.mark.parametrize(
    "change",
    [
        dict(connected=False),
        dict(calibrated=False),
        dict(armed=False),
        dict(source="replay"),
        dict(blocked_reason="poor contact"),
    ],
)
async def test_unready_status_cancels_pending_next(adapter: tuple, change: dict) -> None:
    bci, clock = adapter
    bci.handle_message(trigger(clock()))
    clock.now += 0.01
    bci.handle_message(ready(clock()).model_copy(update=change))
    flush(bci, clock)
    assert not bci.status()["ready"] and bci.scan.moves == 0
    assert bci.badge == "SYNTHETIC SIGNAL"


async def test_stop_restart_does_not_reuse_status_or_pending_input(adapter: tuple) -> None:
    bci, clock = adapter
    bci.handle_message(trigger(clock()))
    await bci.stop()
    await bci.start()
    await bci.set_targets("two", LABELS, "intent")
    flush(bci, clock)
    assert not bci.status()["ready"] and bci.scan.moves == 0


async def test_future_diagnostic_does_not_poison_release_tracking(adapter: tuple) -> None:
    bci, clock = adapter
    await bci.set_targets("two", LABELS, "intent")
    bci.handle_message(levels(clock() + 100))
    clock.now += 0.01
    bci.handle_message(levels(clock()))
    bci.handle_message(trigger(clock(), "select"))
    flush(bci, clock)
    assert (await asyncio.wait_for(anext(bci.selections()), 0.2)).trial_id == "two"


async def test_actual_async_zmq_listener_drops_bad_frames_then_selects() -> None:
    context = zmq.Context()
    publisher = context.socket(zmq.XPUB)
    address = f"inproc://bci-{uuid4()}"
    publisher.bind(address)
    bci = BciInput(
        config=ScanConfig(hold_after_select_s=0),
        sensor=SensorSettings(source="synthetic", pub_address=address),
        context=context,
    )
    try:
        await bci.start()
        async with asyncio.timeout(1):
            while not publisher.poll(0):
                await asyncio.sleep(0.001)
        assert publisher.recv() == b"\x01"
        await bci.set_targets("socket-trial", LABELS, "intent")
        publisher.send(b"not json")
        publisher.send_string(ready(time.time()).model_dump_json())
        # Wait for received readiness, then release, then choose; no artificial sensor connection.
        async with asyncio.timeout(1):
            while not bci.status()["ready"]:
                await asyncio.sleep(0.001)
        publisher.send_string(levels(time.time()).model_dump_json())
        publisher.send_string(trigger(time.time(), "select").model_dump_json())
        selection = await asyncio.wait_for(anext(bci.selections()), 1)
        assert selection.target_idx == 0 and selection.trial_id == "socket-trial"
    finally:
        await bci.stop()
        publisher.close(linger=0)
        context.term()
