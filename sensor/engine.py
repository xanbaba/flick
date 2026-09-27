"""Turns Cortex packets into calibration, trigger levels and trigger events.

Pure logic, no I/O: ``feed(packet, now)`` returns the messages to publish.
Tested with synthetic packets in ``tests/test_sensor.py``; the same code runs
live and in replay.

Signals (both from Cortex ``pow``, band power in uV^2/Hz, 8 Hz, each sample
covering the previous 2 s of EEG):

* next  — jaw clench: mean log10 gamma over FC5, FC6, T7, T8
* select — eyes closed: mean log10 alpha over O1, O2

Each is z-scored against a calibration baseline recorded eyes open and
relaxed. No trigger can fire before calibration completes, while a used
sensor's contact quality is below ``min_contact_quality``, before any contact
data has arrived, or across a gap in the data.
"""

from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass, field
from uuid import uuid4

from sensor.messages import TriggerEvent, TriggerLevel
from sensor.settings import BandTrigger, SensorSettings
from sensor.triggers.base import HoldDetector


@dataclass
class Baseline:
    values: list[float] = field(default_factory=list)
    mean: float = 0.0
    sd: float = 1.0

    def finish(self) -> bool:
        if len(self.values) < 10:
            return False
        n = len(self.values)
        self.mean = sum(self.values) / n
        var = sum((v - self.mean) ** 2 for v in self.values) / (n - 1)
        self.sd = math.sqrt(var) or 1e-6
        return True

    def z(self, v: float) -> float:
        return (v - self.mean) / self.sd


class Feature:
    """Mean log10 band power over a set of sensors, from a Cortex pow row."""

    def __init__(self, spec: BandTrigger, pow_cols: list[str]) -> None:
        wanted = [f"{s}/{spec.band}" for s in spec.sensors]
        missing = [w for w in wanted if w not in pow_cols]
        if missing:
            raise ValueError(f"Cortex pow stream lacks columns {missing}")
        self.idx = [pow_cols.index(w) for w in wanted]
        self.sensors = spec.sensors

    def value(self, row: list) -> float | None:
        try:
            vals = [float(row[i]) for i in self.idx]
        except (IndexError, TypeError, ValueError):
            return None
        if any(v <= 0 or math.isnan(v) for v in vals):
            return None
        return sum(math.log10(v) for v in vals) / len(vals)


class TriggerEngine:
    def __init__(self, settings: SensorSettings, cols: dict[str, list]) -> None:
        self.s = settings
        pow_cols = [str(c) for c in cols.get("pow", [])]
        self.pow_sensors = sorted(
            {c.split("/")[0] for c in pow_cols},
            key=lambda x: [c.split("/")[0] for c in pow_cols].index(x),
        )
        self.pow_bands = sorted(
            {c.split("/")[1] for c in pow_cols},
            key=lambda x: [c.split("/")[1] for c in pow_cols].index(x),
        )
        self.pow_cols = pow_cols
        self.f_next = Feature(settings.next, pow_cols)
        self.f_select = Feature(settings.select, pow_cols)
        self.d_next = HoldDetector(
            settings.next.z_threshold,
            settings.next.hold_s,
            settings.next.refractory_s,
            settings.max_sample_gap_s,
        )
        self.d_select = HoldDetector(
            settings.select.z_threshold,
            settings.select.hold_s,
            settings.select.refractory_s,
            settings.max_sample_gap_s,
        )
        self.dev_cols = cols.get("dev", [])
        self.fac_cols = cols.get("fac", [])
        self.contact: dict[str, int] = {}
        self.battery: int | None = None
        self.eeg_quality: float | None = None
        self.last_contact_t: float | None = None
        self.last_pow_t: float | None = None
        self.facial_action: str | None = None
        self.facial_power = 0.0
        self.shared_quiet_until = float("-inf")
        self.jaw_during_select_hold = 0.0
        self.start_calibration(None)

    # ------------------------------------------------------------ calibration

    def start_calibration(self, now: float | None) -> None:
        self.calibrating = True
        self.cal_start: float | None = now
        self.b_next, self.b_select = Baseline(), Baseline()
        self.calibrated = False
        self.d_next.disarm()
        self.d_select.disarm()

    @property
    def calibration_progress(self) -> float:
        if self.calibrated:
            return 1.0
        if self.cal_start is None or self.last_pow_t is None:
            return 0.0
        return max(0.0, min(1.0, (self.last_pow_t - self.cal_start) / self.s.calibration_s))

    def _calibrate(self, t: float, v_next: float, v_select: float) -> None:
        if self.cal_start is None:
            self.cal_start = t
        self.b_next.values.append(v_next)
        self.b_select.values.append(v_select)
        if t - self.cal_start >= self.s.calibration_s:
            expected = self.s.calibration_s * 8.0 * self.s.min_calibration_fraction
            if (
                len(self.b_next.values) >= expected
                and self.b_next.finish()
                and self.b_select.finish()
            ):
                self.calibrating, self.calibrated = False, True
            else:  # too few samples (gaps, bad contact): start over
                self.start_calibration(t)

    # ---------------------------------------------------------------- gating

    def blocked_reason(self, t: float) -> str | None:
        if not self.calibrated:
            return "calibrating" if self.calibrating else "not calibrated"
        if self.last_contact_t is None:
            return "no contact-quality data yet"
        needed = set(self.s.next.sensors) | set(self.s.select.sensors)
        bad = sorted(s for s in needed if self.contact.get(s, -1) < self.s.min_contact_quality)
        if bad:
            return f"poor contact: {', '.join(bad)}"
        if self.last_pow_t is None or t - self.last_pow_t > self.s.max_sample_gap_s:
            return "no fresh band-power data"
        return None

    # ------------------------------------------------------------------ feed

    def feed(self, packet: dict, now: float) -> list:
        """Process one Cortex packet. Returns messages to publish."""
        out: list = []
        t = float(packet.get("time", now))
        if "dev" in packet:
            self._dev(packet["dev"], t)
        if "eq" in packet:
            self._eq(packet["eq"])
        if "fac" in packet:
            row = packet["fac"]
            with contextlib.suppress(IndexError, TypeError, ValueError):
                self.facial_action, self.facial_power = str(row[3]), float(row[4] or 0)
        if "pow" not in packet:
            return out
        row = packet["pow"]
        v_next, v_select = self.f_next.value(row), self.f_select.value(row)
        if v_next is None or v_select is None:
            return out
        if self.last_pow_t is not None and t - self.last_pow_t > self.s.max_sample_gap_s:
            self.d_next.disarm()
            self.d_select.disarm()
        self.last_pow_t = t
        if self.calibrating:
            if self.last_contact_t is not None and not self._contact_bad():
                self._calibrate(t, v_next, v_select)
            return out
        if not self.calibrated:
            return out

        z_next, z_select = self.b_next.z(v_next), self.b_select.z(v_select)
        armed = self.blocked_reason(t) is None
        out.append(
            TriggerLevel(
                ts=now,
                next_level=round(z_next, 3),
                next_threshold=self.s.next.z_threshold,
                select_level=round(z_select, 3),
                select_threshold=self.s.select.z_threshold,
                facial_action=self.facial_action,
                facial_power=self.facial_power,
            )
        )

        if self.d_select.start is not None or z_select >= self.s.select.z_threshold:
            self.jaw_during_select_hold = max(self.jaw_during_select_hold, z_next)
        r_next = self.d_next.update(t, z_next, armed=armed, blocked_until=self.shared_quiet_until)
        if r_next.fired:
            self.shared_quiet_until = t + self.s.shared_refractory_s
            out.append(
                TriggerEvent(
                    event_id=str(uuid4()),
                    ts=now,
                    source_ts=t,
                    role="next",
                    kind="jaw_clench",
                    strength=r_next.strength,
                )
            )
        r_sel = self.d_select.update(
            t, z_select, armed=armed, blocked_until=self.shared_quiet_until
        )
        if r_sel.fired:
            self.shared_quiet_until = t + self.s.shared_refractory_s
            out.append(
                TriggerEvent(
                    event_id=str(uuid4()),
                    ts=now,
                    source_ts=t,
                    role="select",
                    kind="eyes_closed",
                    strength=r_sel.strength,
                    contaminated=self.jaw_during_select_hold >= self.s.contamination_z,
                )
            )
        if z_select < self.s.select.z_threshold and self.d_select.start is None:
            self.jaw_during_select_hold = 0.0
        return out

    def _contact_bad(self) -> bool:
        needed = set(self.s.next.sensors) | set(self.s.select.sensors)
        return any(self.contact.get(s, -1) < self.s.min_contact_quality for s in needed)

    def _dev(self, row: list, t: float) -> None:
        """Cortex dev: [battery level, signal, [per-sensor quality..., overall], battery %].
        Sensor names come from the subscribe response columns, never positions."""
        names = next((c for c in self.dev_cols if isinstance(c, list)), None)
        values = next((v for v in row if isinstance(v, list)), None)
        if names and values:
            self.contact = {
                str(n): int(v)
                for n, v in zip(names, values, strict=False)
                if isinstance(v, (int, float))
            }
            self.last_contact_t = t
        with contextlib.suppress(TypeError, ValueError, IndexError):
            self.battery = int(row[-1])

    def _eq(self, row: list) -> None:
        with contextlib.suppress(TypeError, ValueError, IndexError):
            self.eeg_quality = float(row[1])

    def bandpower_matrix(self, row: list) -> list[list[float]]:
        nb = len(self.pow_bands)
        return [[float(row[i * nb + j]) for j in range(nb)] for i in range(len(self.pow_sensors))]
