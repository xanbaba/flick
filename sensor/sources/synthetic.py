"""Synthetic Cortex-shaped source, for tests and for working without a headset.

Plays a fixed scenario at 8 Hz band-power rate: eyes-open rest for the
calibration, then jaw clenches (raised gamma on FC5/FC6/T7/T8) and eyes-closed
periods (raised alpha on O1/O2). Numbers are shaped like Cortex output, not
recorded data.
"""

from __future__ import annotations

import random
import threading
import time

from sensor.sources.base import OnPacket

SENSORS = ["AF3", "F7", "F3", "FC5", "T7", "P7", "O1", "O2", "P8", "T8", "FC6", "F4", "F8", "AF4"]
BANDS = ["theta", "alpha", "betaL", "betaH", "gamma"]
BASE = {"theta": 4.0, "alpha": 3.0, "betaL": 1.5, "betaH": 0.8, "gamma": 0.3}
JAW = {"FC5", "FC6", "T7", "T8"}
OCC = {"O1", "O2"}
POW_HZ = 8.0


def cols() -> dict[str, list]:
    return {
        "pow": [f"{s}/{b}" for s in SENSORS for b in BANDS],
        "dev": ["Battery", "Signal", [*SENSORS, "OVERALL"], "BatteryPercent"],
        "eq": ["batteryPercent", "overall", "sampleRateQuality", *SENSORS],
        "fac": ["eyeAct", "uAct", "uPow", "lAct", "lPow"],
    }


def default_scenario(calibration_s: float = 20.0) -> list[tuple[str, float]]:
    """(state, seconds): rest, then 3 clenches, then 2 eyes-closed periods."""
    s: list[tuple[str, float]] = [("rest", calibration_s + 3)]
    for _ in range(3):
        s += [("clench", 1.0), ("rest", 3.0)]
    for _ in range(2):
        s += [("eyes", 2.5), ("rest", 5.0)]
    return s


def pow_row(state: str, rng: random.Random) -> list[float]:
    row = []
    for s in SENSORS:
        for b in BANDS:
            v = BASE[b] * 10 ** rng.gauss(0, 0.04)
            if state in ("clench", "both") and s in JAW and b in ("gamma", "betaH"):
                v *= 40.0
            if state in ("eyes", "both") and s in OCC and b == "alpha":
                v *= 4.0
            row.append(round(v, 4))
    return row


def packets(scenario: list[tuple[str, float]], seed: int = 0, t0: float = 0.0, contact: int = 4):
    """Yield (t, packet) for a whole scenario, contact data once per second.

    States: ``rest``, ``clench``, ``eyes`` (closed), ``both``, ``gap`` (no data).
    """
    rng = random.Random(seed)
    t = t0
    k = 0
    for state, dur in scenario:
        for _ in range(round(dur * POW_HZ)):
            if state == "gap":
                t += 1.0 / POW_HZ
                continue
            if k % 8 == 0:
                yield t, {"dev": [4, 2, [contact] * len(SENSORS) + [100], 90], "time": t}
                yield t, {"eq": [90, 100, 1.0, *([4] * len(SENSORS))], "time": t}
            fac = [
                "neutral",
                "neutral",
                0.0,
                "clench" if state == "clench" else "neutral",
                0.8 if state == "clench" else 0.0,
            ]
            yield t, {"fac": fac, "time": t}
            yield t, {"pow": pow_row(state, rng), "time": t}
            t += 1.0 / POW_HZ
            k += 1


class SyntheticSource:
    name = "synthetic"

    def __init__(
        self, scenario: list[tuple[str, float]] | None = None, loop: bool = True, seed: int = 0
    ) -> None:
        self.scenario = scenario or default_scenario()
        self.loop = loop
        self.seed = seed
        self.headset_id = "SYNTHETIC"
        self.connected = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, on_packet: OnPacket) -> dict[str, list]:
        def run() -> None:
            start = time.time()
            seed = self.seed
            while not self._stop.is_set():
                for t, p in packets(self.scenario, seed, t0=start):
                    delay = t - time.time()
                    if delay > 0 and self._stop.wait(delay):
                        return
                    on_packet(p)
                if not self.loop:
                    return
                start, seed = time.time(), seed + 1

        self.connected = True
        self._thread = threading.Thread(target=run, name="synthetic-source", daemon=True)
        self._thread.start()
        return cols()

    def close(self) -> None:
        self._stop.set()
        self.connected = False
