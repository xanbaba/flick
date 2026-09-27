"""inputs/keyboard.py — the development adapter (ARCHITECTURE.md section 7.2).

Build this first. It unblocks the entire team.

Number keys 1-5, sent by the dashboard over the backend WebSocket as
a client.key_press message (section 6.3), each produce a Selection
with confidence 1.0 and source "keyboard". The persistent orange
KEYBOARD INPUT badge is DEMO-3's enforcement in code that this is a
development tool, never used in front of judges.

This module has no knowledge of WebSockets or FastAPI (both live in
backend/, out of scope here). The backend's WS handler is expected to
call handle_key_press() with the raw client.key_press payload it
received. KeyPress carries no trial_id (section 6.3): the adapter
attaches whichever trial_id is currently on screen from its own
set_targets() state, so a key press arriving with no active trial
(or after that trial already produced a Selection) is dropped rather
than guessed at.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from pydantic import ValidationError

from inputs.base import InputSource
from shared.logging import get_logger
from shared.schemas import KeyPress, Selection

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
        self._active_targets: set[int] = set()

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False
        self._current_trial_id = None
        self._active_targets.clear()
        while not self._queue.empty():
            self._queue.get_nowait()

    async def set_targets(self, trial_id: str, labels: list[str], round: str) -> None:
        self._current_trial_id = trial_id
        self._active_targets = {
            i for i, label in enumerate(labels[: self.n_targets]) if label.strip()
        }

    def handle_key_press(self, raw: KeyPress | dict | str | bytes) -> None:
        """Consume a raw client.key_press payload from the backend's WS layer.

        Invalid messages (fails KeyPress validation, or a non-numeric
        or out-of-range key) are logged and dropped, never raised to
        the caller. Drops the event if there is no trial currently on
        screen (stale or absent). Clears the active trial after
        accepting one key press, so at most one Selection is ever
        emitted per trial_id.
        """
        message = self._parse(raw)
        if message is None:
            return

        if self._current_trial_id is None:
            logger.debug("keyboard.key_press_dropped_no_active_trial")
            return

        try:
            key = int(message.key)
        except ValueError:
            logger.warning("keyboard.non_numeric_key_dropped", key=message.key)
            return

        if not (1 <= key <= self.n_targets):
            logger.warning("keyboard.key_out_of_range", key=key)
            return
        if key - 1 not in self._active_targets:
            logger.debug("keyboard.inactive_target_dropped", key=key)
            return

        selection = Selection(
            type="input.selection",
            ts=time.time(),
            trial_id=self._current_trial_id,
            target_idx=key - 1,
            confidence=1.0,
            source=self.name,
            algorithm=None,
        )
        self._current_trial_id = None  # at most one Selection per trial_id
        self._queue.put_nowait(selection)

    def _parse(self, raw: KeyPress | dict | str | bytes) -> KeyPress | None:
        try:
            if isinstance(raw, KeyPress):
                return raw
            if isinstance(raw, str | bytes):
                return KeyPress.model_validate_json(raw)
            return KeyPress.model_validate(raw)
        except ValidationError:
            logger.warning("keyboard.invalid_key_press_dropped")
            return None

    async def selections(self) -> AsyncIterator[Selection]:
        while True:
            yield await self._queue.get()

    def status(self) -> dict:
        return {
            "started": self._started,
            "current_trial_id": self._current_trial_id,
        }
