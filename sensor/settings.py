"""P1 sensor settings.

Defaults are the values measured on the headset on 2026-09-27 (see
CHANGELOG.md, "Trigger tests on the headset"). They are read from a
``sensor:`` section of ``config.yaml`` when one exists; until the
coordinated contract/config commit (ARCHITECTURE.md §5, AGENTS.md §4) adds
that section, the defaults below apply. Nothing here is a secret: Cortex
credentials come from ``.env`` via ``shared.config.EnvSettings``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class BandTrigger(BaseModel):
    """A trigger that fires when z-scored log band power stays high.

    ``z`` is measured against the eyes-open, relaxed calibration baseline,
    averaged over ``sensors`` in ``band`` (Cortex pow band names).
    """

    sensors: list[str]
    band: Literal["theta", "alpha", "betaL", "betaH", "gamma"]
    z_threshold: float = Field(gt=0)
    hold_s: float = Field(gt=0)
    refractory_s: float = Field(ge=0)  # own refractory, on top of the shared one


class SensorSettings(BaseModel):
    source: Literal["emotiv", "synthetic", "replay"] = "emotiv"
    replay_file: str | None = None

    cortex_url: str = "wss://localhost:6868"
    headset_id: str | None = None

    pub_address: str = "tcp://127.0.0.1:5555"
    control_address: str = "tcp://127.0.0.1:5556"

    calibration_s: float = Field(default=20.0, gt=5)
    min_calibration_fraction: float = Field(default=0.6, gt=0, le=1)
    min_contact_quality: int = Field(default=3, ge=0, le=4)
    max_sample_gap_s: float = Field(default=0.5, gt=0)
    shared_refractory_s: float = Field(default=0.8, ge=0)
    contamination_z: float = Field(default=4.0, gt=0)
    status_hz: float = Field(default=1.0, gt=0)

    # next = jaw clench, read from jaw-muscle activity in the gamma band on the
    # side sensors. Emotiv's facial labels called a clench smile/smirk/laugh,
    # so the label is not used. Measured: 10/10, 0 false (rest, talking).
    next: BandTrigger = BandTrigger(
        sensors=["FC5", "FC6", "T7", "T8"],
        band="gamma",
        z_threshold=8.0,
        hold_s=0.25,
        refractory_s=0.0,
    )
    # select = eyes closed ~2 s, read from alpha over the visual cortex.
    # Measured: 10/10, 0 false with eyes open, ~2 s delay. Alpha stays raised
    # ~2 s after the eyes open, hence the 3 s own refractory.
    select: BandTrigger = BandTrigger(
        sensors=["O1", "O2"],
        band="alpha",
        z_threshold=2.0,
        hold_s=0.5,
        refractory_s=3.0,
    )

    record: bool = True
    record_dir: Path = Path("data/sessions")
    record_queue_max: int = Field(default=20_000, gt=0)

    @model_validator(mode="after")
    def _distinct_signals(self) -> SensorSettings:
        if set(self.next.sensors) & set(self.select.sensors) and self.next.band == self.select.band:
            raise ValueError("next and select must read different sensor/band features")
        return self


def load_settings(path: Path | str = "config.yaml", **overrides: object) -> SensorSettings:
    """Defaults, then config.yaml's optional ``sensor:`` section, then overrides."""
    data: dict = {}
    p = Path(path)
    if p.exists():
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        section = raw.get("sensor")
        if isinstance(section, dict):
            data.update(section)
    data.update({k: v for k, v in overrides.items() if v is not None})
    return SensorSettings.model_validate(data)
