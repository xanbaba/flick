"""Keyboard input using the same scan state machine as Cortex.

The legacy five-slot UI retains numeric picks without a trial ID. Four-slot
scan mode requires the displayed trial ID for n/s and numeric picks.
"""

from __future__ import annotations

from pydantic import ValidationError

from inputs.scan import ScanInput
from shared.config import ScanConfig
from shared.logging import get_logger
from shared.schemas import KeyPress

logger = get_logger(__name__)


class KeyboardInput(ScanInput):
    name = "keyboard"
    badge = "KEYBOARD INPUT"

    def __init__(self, n_targets: int = 5, *, config: ScanConfig | None = None) -> None:
        self._legacy = n_targets == 5 and config is None
        super().__init__(
            config or ScanConfig(hold_after_select_s=0 if self._legacy else 0.6),
            n_targets=n_targets,
        )

    def handle_key_press(self, raw: KeyPress | dict | str | bytes) -> None:
        try:
            if isinstance(raw, KeyPress):
                message = raw
            elif isinstance(raw, str | bytes):
                message = KeyPress.model_validate_json(raw)
            else:
                message = KeyPress.model_validate(raw)
        except ValidationError:
            logger.warning("keyboard.invalid_key_press_dropped")
            return
        if not self._started or not self.scan.active():
            return
        if message.trial_id != self.scan.trial_id and not (
            self._legacy and message.trial_id is None and message.key in "12345"
        ):
            return
        age = self.scan.wall_clock() - message.ts
        if not (-self.config.clock_tolerance_s <= age <= self.config.event_max_age_s):
            return
        if message.ts < self.scan.activated_at:
            return
        if message.key == "n":
            self.scan.advance()
        elif message.key == "s":
            self.scan.select(source=self.name)
        elif message.key in [str(index + 1) for index in range(self.n_targets)]:
            self.scan.select(source=self.name, target_idx=int(message.key) - 1)
        self.tick()
