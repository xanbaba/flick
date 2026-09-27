"""P1 ↔ P3 messages (ARCHITECTURE.md §6.2–§6.3, target contract).

These live here until the coordinated contract commit moves them into
``shared/schemas.py`` and ``frontend/src/lib/types.ts`` (AGENTS.md §4).
Field names follow §6.2. Changes from §6.2, proposed for that commit:

* ``TriggerEvent.kind`` is ``jaw_clench`` (next) or ``eyes_closed`` (select).
* ``TriggerLevel`` levels/thresholds are z-scores against the calibration
  baseline, not 0..1 Cortex powers.
* ``TriggerEvent.contaminated`` applies to ``select``: jaw-muscle activity
  overlapping the eyes-closed hold.
* ``SensorStatus`` adds ``calibrated`` / ``calibration_progress``; with no
  mental command, ``profile_loaded`` / ``trained_actions`` stay False / [].
* ``SensorControl`` adds ``calibrate``; training actions are not used.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BandPowerFrame(BaseModel):
    type: Literal["bci.bandpower"] = "bci.bandpower"
    ts: float
    sensors: list[str]
    bands: list[str]
    power: list[list[float]]  # [sensor][band], uV^2/Hz as reported by Cortex


class TriggerLevel(BaseModel):
    type: Literal["bci.trigger_level"] = "bci.trigger_level"
    ts: float
    next_level: float  # z
    next_threshold: float  # z
    select_level: float  # z
    select_threshold: float  # z
    facial_action: str | None = None
    facial_power: float = 0.0


class TriggerEvent(BaseModel):
    type: Literal["bci.trigger"] = "bci.trigger"
    ts: float  # local clock, when the hold completed
    source_ts: float  # Cortex timestamp of the completing sample
    role: Literal["next", "select"]
    kind: Literal["jaw_clench", "eyes_closed"]
    strength: float = Field(ge=0, le=1)
    contaminated: bool = False


class SensorStatus(BaseModel):
    type: Literal["bci.status"] = "bci.status"
    ts: float
    source: Literal["emotiv", "synthetic", "replay"]
    connected: bool
    headset_id: str | None = None
    battery_pct: int | None = None
    contact_quality: dict[str, int] = {}
    eeg_quality: float | None = None
    streams: list[str] = []
    next_trigger: str = "jaw_clench"
    select_trigger: str = "eyes_closed"
    calibrated: bool = False
    calibration_progress: float = 0.0  # 0..1
    armed: bool = False  # calibrated, fresh data, contact OK
    blocked_reason: str | None = None
    profile_loaded: bool = False
    trained_actions: list[str] = []
    dropped_samples: int = 0


class SensorControl(BaseModel):
    type: Literal["sensor.control"] = "sensor.control"
    ts: float
    action: Literal["calibrate", "train", "train_accept", "train_reject", "reload_profile"]
    train_action: str | None = None
