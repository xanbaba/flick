"""inputs/ssvep.py — the production adapter (ARCHITECTURE.md section 7.3).

Subscribes to P1 sensor's Selection stream on ZMQ 5555 and forwards
it with source "ssvep". Calls set_targets by publishing
stim.show_targets on ZMQ 5556 for P2 stimulus to render. badge is
None: this is the only adapter with a null badge, which is how
DEMO-1 and DEMO-3 are enforced in code (section 7.6).

P1 sensor and P2 stimulus do not exist yet in this build (sensor/ and
stimulus/ are out of scope). This adapter is written against the
frozen contracts in shared/schemas.py and will work unmodified once
they exist — the ZMQ link is real, only the other end is missing.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from pydantic import ValidationError

from inputs.base import InputSource
from shared.bus import Publisher, Subscriber
from shared.logging import get_logger
from shared.schemas import Selection, ShowTargets

logger = get_logger(__name__)

SENSOR_ADDRESS = "tcp://127.0.0.1:5555"
STIMULUS_ADDRESS = "tcp://127.0.0.1:5556"

# How long a poll on the sensor SUB socket may block before yielding
# control back to the event loop. Not a DSP or stimulus constant, so
# it is not required to live in config.yaml per AGENTS.md section 7.2.
_POLL_TIMEOUT_MS = 50


class SsvepInput(InputSource):
    """The real path: EEG through P1's classifier to a Selection."""

    name = "ssvep"
    badge: str | None = None
    supports_labels = True

    def __init__(
        self,
        n_targets: int = 5,
        *,
        sensor_address: str = SENSOR_ADDRESS,
        stimulus_address: str = STIMULUS_ADDRESS,
    ) -> None:
        self.n_targets = n_targets
        self._sensor_address = sensor_address
        self._stimulus_address = stimulus_address
        self._subscriber: Subscriber | None = None
        self._publisher: Publisher | None = None
        self._current_trial_id: str | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[Selection] = asyncio.Queue()

    async def start(self) -> None:
        self._subscriber = Subscriber(self._sensor_address)
        self._publisher = Publisher(self._stimulus_address)
        self._listen_task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._listen_task is not None:
            self._listen_task.cancel()
            self._listen_task = None
        if self._subscriber is not None:
            self._subscriber.close()
            self._subscriber = None
        if self._publisher is not None:
            self._publisher.close()
            self._publisher = None
        self._current_trial_id = None

    async def set_targets(self, trial_id: str, labels: list[str], round: str) -> None:
        if self._publisher is None:
            raise RuntimeError(f"{self.name} input is not started")
        self._current_trial_id = trial_id
        self._publisher.send(
            ShowTargets(
                type="stim.show_targets",
                ts=time.time(),
                trial_id=trial_id,
                labels=labels,
                round=round,
                cue_idx=None,
            )
        )

    async def selections(self) -> AsyncIterator[Selection]:
        while True:
            yield await self._queue.get()

    def status(self) -> dict:
        return {
            "connected": self._subscriber is not None,
            "current_trial_id": self._current_trial_id,
        }

    async def _listen(self) -> None:
        """Relay Selections from the sensor bus, dropping stale trials."""
        assert self._subscriber is not None
        subscriber = self._subscriber
        while True:
            if subscriber.poll(timeout_ms=_POLL_TIMEOUT_MS):
                try:
                    selection = subscriber.recv_as(Selection)
                except ValidationError:
                    logger.warning(f"{self.name}.malformed_frame_dropped")
                    continue
                if selection.trial_id != self._current_trial_id:
                    logger.debug(
                        f"{self.name}.stale_selection_dropped",
                        trial_id=selection.trial_id,
                    )
                    continue
                self._current_trial_id = None  # at most one Selection per trial_id
                self._queue.put_nowait(selection.model_copy(update={"source": self.name}))
            else:
                await asyncio.sleep(0)
