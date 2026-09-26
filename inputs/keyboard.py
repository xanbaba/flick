"""inputs/keyboard.py — the development adapter (ARCHITECTURE.md section 7.2).

Build this first. It unblocks the entire team.

Number keys 1-5, sent by the dashboard over the backend WebSocket,
each produce a Selection with confidence 1.0 and source "keyboard".
The persistent orange KEYBOARD INPUT badge is DEMO-3's enforcement in
code that this is a development tool, never used in front of judges.

This module has no knowledge of WebSockets or FastAPI (both live in
backend/, out of scope here). The backend's WS handler is expected to
call on_keypress() with the trial_id it last showed on the dashboard
and the digit the pilot pressed.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from inputs.base import InputSource
from shared.logging import get_logger
from shared.schemas import Selection

logger = get_logger(__name__)


class KeyboardInput(InputSource):
    """Dev-only adapter: no headset, no gel, no signal processing."""

    name = "keyboard"
    badge: str | None = "KEYBOARD INPUT"
    supports_labels = True

    def __init__(self, n_targets: int = 5) -> None:
        self.n_targets = n_targets
        self._current_trial_id: str | None = None
        self._queue: asyncio.Queue[Selection] = asyncio.Queue()
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False
        self._current_trial_id = None

    async def set_targets(self, trial_id: str, labels: list[str], round: str) -> None:
        self._current_trial_id = trial_id

    def on_keypress(self, trial_id: str, key: int) -> None:
        """Feed one number-key event (1..n_targets) from the WebSocket.

        Drops the event if trial_id does not match the trial currently
        on screen (stale), or if the digit is out of range. Clears the
        active trial after accepting one keypress, so at most one
        Selection is ever emitted per trial_id.
        """
        if trial_id != self._current_trial_id:
            logger.debug("keyboard.stale_selection_dropped", trial_id=trial_id)
            return
        if not (1 <= key <= self.n_targets):
            logger.warning("keyboard.key_out_of_range", key=key)
            return

        selection = Selection(
            type="input.selection",
            ts=time.time(),
            trial_id=trial_id,
            target_idx=key - 1,
            confidence=1.0,
            source=self.name,
            algorithm=None,
        )
        self._current_trial_id = None  # at most one Selection per trial_id
        self._queue.put_nowait(selection)

    async def selections(self) -> AsyncIterator[Selection]:
        while True:
            yield await self._queue.get()

    def status(self) -> dict:
        return {
            "started": self._started,
            "current_trial_id": self._current_trial_id,
        }
