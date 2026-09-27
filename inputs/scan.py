"""Authoritative, timer-independent step scan state shared by input adapters."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable

from inputs.base import InputSource
from shared.config import ScanConfig
from shared.schemas import Selection

ScanEvent = tuple[str, dict[str, object]]


class ScanController:
    def __init__(
        self,
        config: ScanConfig,
        *,
        n_targets: int = 4,
        emit: Callable[[str, dict[str, object]], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.n_targets = n_targets
        self._emit = emit or (lambda kind, payload: None)
        self.clock, self.wall_clock = clock, wall_clock
        self.trial_id: str | None = None
        self.labels: list[str] = []
        self.round = ""
        self.highlight_idx = 0
        self.moves = 0
        self.activated_at = 0.0
        self.deadline = 0.0
        self._pending: Selection | None = None
        self._hold_until = 0.0
        self._used_trials: set[str] = set()

    def set_targets(self, trial_id: str, labels: list[str], round: str) -> None:
        if self._pending is not None:
            raise RuntimeError("selection confirmation is still in progress")
        if not trial_id or trial_id in self._used_trials:
            raise ValueError("each trial must have a fresh nonempty ID")
        if len(labels) != self.n_targets or labels[-1] != "Cancel":
            raise ValueError("targets must have the configured slot count and final Cancel")
        if round not in ("intent", "candidate", "speller"):
            raise ValueError("unknown selection round")
        if not any(label.strip() for label in labels[:-1]):
            raise ValueError("at least one non-Cancel target must be enabled")
        if self.trial_id is not None:
            self.close("replaced")
        self._used_trials.add(trial_id)
        self.trial_id, self.labels, self.round = trial_id, list(labels), round
        self.moves = 0
        self.activated_at = self.wall_clock()
        self.deadline = self.clock() + self.config.trial_timeout_s
        for offset in range(self.n_targets):
            index = (self.config.start_idx + offset) % self.n_targets
            if self.labels[index].strip():
                self.highlight_idx = index
                break
        self._emit("scan.targets", self.snapshot())

    def snapshot(self) -> dict[str, object]:
        return dict(
            trial_id=self.trial_id,
            labels=list(self.labels),
            round=self.round,
            cancel_idx=self.n_targets - 1,
            highlight_idx=self.highlight_idx,
        )

    def active(self) -> bool:
        if self.trial_id is not None and self.clock() >= self.deadline:
            self.close("timeout")
        return self.trial_id is not None

    def advance(self) -> None:
        if not self.active():
            return
        for offset in range(1, self.n_targets + 1):
            index = (self.highlight_idx + offset) % self.n_targets
            if self.labels[index].strip():
                self.highlight_idx = index
                self.moves += 1
                self._emit("scan.highlight", dict(trial_id=self.trial_id, highlight_idx=index))
                return

    def select(
        self,
        *,
        source: str,
        confidence: float = 1.0,
        trigger_kind: str | None = None,
        target_idx: int | None = None,
    ) -> None:
        if not self.active():
            return
        index = self.highlight_idx if target_idx is None else target_idx
        if not 0 <= index < len(self.labels) or not self.labels[index].strip():
            return
        selection = Selection(
            type="input.selection",
            ts=self.wall_clock(),
            trial_id=self.trial_id,
            target_idx=index,
            confidence=confidence,
            source=source,
            algorithm="step_scan" if source == "bci" else None,
            trigger_kind=trigger_kind,
            moves=self.moves,
        )
        self._pending = selection
        self.trial_id = None  # close atomically before publishing anything
        self._hold_until = self.clock() + self.config.hold_after_select_s
        self._emit(
            "scan.selected",
            dict(
                trial_id=selection.trial_id,
                target_idx=index,
                hold_s=self.config.hold_after_select_s,
            ),
        )

    def tick(self) -> Selection | None:
        self.active()
        if self._pending is not None and self.clock() >= self._hold_until:
            selection, self._pending = self._pending, None
            self._emit("scan.idle", dict(trial_id=selection.trial_id, reason="selected"))
            return selection
        return None

    def close(self, reason: str = "closed") -> None:
        trial = self.trial_id or (self._pending.trial_id if self._pending else None)
        self.trial_id, self._pending = None, None
        if trial is not None:
            self._emit("scan.idle", dict(trial_id=trial, reason=reason))


class ScanInput(InputSource):
    """Lifecycle/queues shared by keyboard and Cortex, confined to one event loop."""

    supports_labels = True

    def __init__(self, config: ScanConfig, *, n_targets: int = 4) -> None:
        self.n_targets = n_targets
        self.config = config
        self._events: asyncio.Queue[ScanEvent] = asyncio.Queue()
        self._queue: asyncio.Queue[Selection] = asyncio.Queue(maxsize=1)
        self.scan = ScanController(config, n_targets=n_targets, emit=self._emit)
        self._started = False
        self._timer: asyncio.Task[None] | None = None

    def _emit(self, kind: str, payload: dict[str, object]) -> None:
        self._events.put_nowait((kind, payload))

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._timer = asyncio.create_task(self._maintain())

    async def stop(self) -> None:
        self._started = False
        if self._timer is not None:
            self._timer.cancel()
            await asyncio.gather(self._timer, return_exceptions=True)
            self._timer = None
        self.close_trial("stopped")
        while not self._events.empty():
            self._events.get_nowait()

    def close_trial(self, reason: str = "closed") -> None:
        self.scan.close(reason)
        while not self._queue.empty():
            self._queue.get_nowait()

    async def set_targets(self, trial_id: str, labels: list[str], round: str) -> None:
        if not self._started:
            raise RuntimeError("input is not started")
        self.scan.set_targets(trial_id, labels, round)
        while not self._queue.empty():
            self._queue.get_nowait()

    def tick(self) -> None:
        selection = self.scan.tick()
        if selection is not None:
            self._queue.put_nowait(selection)

    async def _maintain(self) -> None:
        while self._started:
            self.tick()
            await asyncio.sleep(self.config.poll_interval_s)

    async def selections(self) -> AsyncIterator[Selection]:
        while self._started:
            yield await self._queue.get()

    async def events(self) -> AsyncIterator[ScanEvent]:
        while self._started:
            yield await self._events.get()

    def status(self) -> dict:
        return {"started": self._started, "current_trial_id": self.scan.trial_id}
