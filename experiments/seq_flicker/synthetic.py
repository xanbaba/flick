"""Synthetic Cortex-shaped streams, for dry runs without a headset.

This exists to test the runner and the analysis end to end. It is NOT
evidence that the method works: the effect size is whatever you pass in.
Sessions recorded with it are marked "synthetic" in meta.json and the
report says so on its first line.

Model: log10 band power per sensor/band = baseline + AR(1) noise. While a
tile flickers, occipital (O1/O2) betaL and gamma rise in proportion to a
"drive": 1.0 when the flickering tile is the one being looked at (or all
tiles flicker), 0.3 when it is in peripheral vision, 0 when nothing
flickers. Like Cortex, each sample reflects the last 2 s (plus a small
processing lag), so the response ramps in and out of each slot.
"""

from __future__ import annotations

import random

EPOC_X_SENSORS = [
    "AF3",
    "F7",
    "F3",
    "FC5",
    "T7",
    "P7",
    "O1",
    "O2",
    "P8",
    "T8",
    "FC6",
    "F4",
    "F8",
    "AF4",
]
BANDS = ["theta", "alpha", "betaL", "betaH", "gamma"]
POW_COLS = [f"{s}/{b}" for s in EPOC_X_SENSORS for b in BANDS]
FAC_COLS = ["eyeAct", "uAct", "uPow", "lAct", "lPow"]
DEV_COLS = ["Battery", "Signal", EPOC_X_SENSORS + ["OVERALL"], "BatteryPercent"]

POW_HZ = 8.0
WINDOW_S = 2.0
LAG_S = 0.1
_BASE = {"theta": 0.9, "alpha": 1.1, "betaL": 0.45, "betaH": 0.35, "gamma": 0.1}
_SD = 0.12  # log10 units


def drive_of(seg) -> float:
    """How strongly the flicker on screen reaches central vision."""
    if seg is None:
        return 0.0
    if seg.flicker_all:
        return 1.0
    if seg.active_tile is None:
        return 0.0
    if seg.target is not None and seg.active_tile == seg.target:
        return 1.0
    return 0.3


class SyntheticStreams:
    def __init__(self, effect_sd: float = 1.0, seed: int = 1) -> None:
        self.effect_sd = effect_sd
        self.rng = random.Random(seed)
        self.cols = {"pow": POW_COLS, "fac": FAC_COLS, "dev": DEV_COLS}
        self._noise = {c: 0.0 for c in POW_COLS}
        self._alpha_walk = 0.0
        self.timeline: list[tuple[float, float, object]] = []  # (start, end, segment)
        self._last_blink = 0.0

    def add_segment(self, start: float, end: float, seg) -> None:
        self.timeline.append((start, end, seg))

    def _mean_drive(self, t0: float, t1: float) -> float:
        total = 0.0
        for s, e, seg in self.timeline:
            lo, hi = max(s, t0), min(e, t1)
            if hi > lo:
                total += (hi - lo) * drive_of(seg)
        return total / (t1 - t0)

    def pow_sample(self, t: float) -> dict:
        d = self._mean_drive(t - LAG_S - WINDOW_S, t - LAG_S)
        self._alpha_walk = 0.98 * self._alpha_walk + self.rng.gauss(0, 0.03)
        values = []
        for c in POW_COLS:
            sensor, band = c.split("/")
            n = 0.85 * self._noise[c] + self.rng.gauss(0, (1 - 0.85**2) ** 0.5)
            self._noise[c] = n
            z = n
            if sensor in ("O1", "O2") and band == "betaL":
                z += self.effect_sd * d
            if sensor in ("O1", "O2") and band == "gamma":
                z += 0.4 * self.effect_sd * d
            log_p = _BASE[band] + _SD * z + (self._alpha_walk if band == "alpha" else 0.0)
            values.append(round(10**log_p, 5))
        return {"pow": values, "sid": "synthetic", "time": t}

    def fac_sample(self, t: float) -> dict:
        blink = t - self._last_blink > 4 and self.rng.random() < 0.05
        if blink:
            self._last_blink = t
        return {
            "fac": ["blink" if blink else "neutral", "neutral", 0.0, "neutral", 0.0],
            "sid": "synthetic",
            "time": t,
        }

    def dev_sample(self, t: float) -> dict:
        return {
            "dev": [4, 1.0, [4] * len(EPOC_X_SENSORS) + [100], 90],
            "sid": "synthetic",
            "time": t,
        }
