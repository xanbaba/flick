"""tests/test_telemetry.py — the rule that matters (ARCHITECTURE.md section 18.2).

"The database must never be able to stall the pipeline." Asserts
that with the consumer stalled, 10,000 emit() calls complete in under
50 ms and the dropped counter equals the overflow, and that emit()
never raises regardless of queue state.
"""

from __future__ import annotations

import time

import pytest

from backend.app.services.telemetry import TelemetryService

N_EMITS = 10_000
QUEUE_MAXSIZE = 2000


def _make_service(queue_maxsize: int = QUEUE_MAXSIZE) -> TelemetryService:
    return TelemetryService(
        queue_maxsize=queue_maxsize,
        flush_interval_ms=500,
        flush_batch=500,
        dsn="",
    )


def test_emit_with_a_stalled_consumer_completes_fast_and_drops_the_overflow() -> None:
    service = _make_service()
    # The consumer is never started: this is "stalled" from emit()'s
    # point of view, since emit() never talks to it directly anyway.

    start = time.perf_counter()
    for i in range(N_EMITS):
        service.emit("eeg_frames", {"ts": float(i), "session_id": "s", "ch0": 0.0})
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 50, f"emit() took {elapsed_ms:.2f} ms for {N_EMITS} calls"
    assert service.dropped_count == N_EMITS - QUEUE_MAXSIZE


def test_emit_never_raises_on_an_empty_or_malformed_record() -> None:
    service = _make_service(queue_maxsize=1)
    service.emit("selections", {})
    service.emit("selections", {})  # queue already full: dropped, not raised
    service.emit("bci_scores", {"anything": object()})  # unusual value: still not raised
    assert service.dropped_count == 2


async def test_start_and_stop_do_not_raise_with_no_dsn_configured() -> None:
    service = _make_service()
    await service.start()
    service.emit("turns", {"turn_id": "t1"})
    await service.stop()  # must not hang or raise even mid-flush-cycle


async def test_consumer_drains_the_queue_so_later_emits_are_not_dropped() -> None:
    service = _make_service(queue_maxsize=10)
    for i in range(10):
        service.emit("eeg_frames", {"ts": float(i)})
    assert service.dropped_count == 0

    await service.start()
    try:
        # flush_interval_ms is 500; give the consumer a couple of cycles
        # to drain (dsn="" means each batch is discarded, not written).
        import asyncio

        await asyncio.sleep(1.2)
        service.emit("eeg_frames", {"ts": 99.0})
        assert service.dropped_count == 0
    finally:
        await service.stop()


def test_dropped_count_is_monotonic_and_never_negative() -> None:
    # asyncio.Queue(maxsize=0) means unbounded, not "always full" -- use
    # a queue that is already saturated instead.
    service = _make_service(queue_maxsize=1)
    service.emit("selections", {})  # fills the one slot
    assert service.dropped_count == 0
    for _ in range(5):
        service.emit("selections", {})
    assert service.dropped_count == 5


@pytest.mark.parametrize("queue_maxsize", [1, 50, 100])
def test_dropped_equals_overflow_for_various_queue_sizes(queue_maxsize: int) -> None:
    service = _make_service(queue_maxsize=queue_maxsize)
    for _ in range(500):
        service.emit("selections", {})
    assert service.dropped_count == 500 - queue_maxsize
