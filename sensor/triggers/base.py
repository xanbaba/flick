"""Hold detector shared by every trigger (ARCHITECTURE.md §8.2).

Fires once when its signal stays at or above threshold for ``hold_s`` of
elapsed source time. Resets on a low sample, on a gap longer than
``max_gap_s`` (stale data), or when disarmed. After firing it must see the
signal drop below threshold (release) before it can fire again, and it stays
quiet for its own ``refractory_s``. The shared refractory between roles is
applied by the engine.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HoldResult:
    fired: bool
    strength: float = 0.0


class HoldDetector:
    def __init__(
        self, threshold: float, hold_s: float, refractory_s: float, max_gap_s: float
    ) -> None:
        self.threshold = threshold
        self.hold_s = hold_s
        self.refractory_s = refractory_s
        self.max_gap_s = max_gap_s
        self.reset()
        self.quiet_until = float("-inf")

    def reset(self) -> None:
        self.start: float | None = None
        self.last_t: float | None = None
        self.need_release = getattr(self, "need_release", False)
        self.peak = 0.0

    def update(self, t: float, value: float, *, armed: bool, blocked_until: float) -> HoldResult:
        """Feed one sample. ``blocked_until`` is the shared refractory end."""
        if self.last_t is not None and t - self.last_t > self.max_gap_s:
            self.start = None  # stale: never carry a hold across a gap
        self.last_t = t
        above = value >= self.threshold
        if not above:
            self.start = None
            self.need_release = False
            self.peak = 0.0
            return HoldResult(False)
        if not armed or self.need_release or t < self.quiet_until or t < blocked_until:
            self.start = None
            return HoldResult(False)
        if self.start is None:
            self.start = t
            self.peak = value
        self.peak = max(self.peak, value)
        if t - self.start >= self.hold_s:
            self.start = None
            self.need_release = True
            self.quiet_until = t + self.refractory_s
            # strength: how far the peak cleared the threshold, 1.0 at 2x threshold
            strength = max(0.0, min(1.0, (self.peak - self.threshold) / self.threshold))
            return HoldResult(True, strength)
        return HoldResult(False)

    def disarm(self) -> None:
        self.start = None
