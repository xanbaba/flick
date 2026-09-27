"""P1 settings loader; model definitions are shared with the backend."""

from __future__ import annotations

from pathlib import Path

import yaml

from shared.config import BandTrigger, SensorSettings

__all__ = ["BandTrigger", "SensorSettings", "load_settings"]


def load_settings(path: Path | str = "config.yaml", **overrides: object) -> SensorSettings:
    """Defaults, then config.yaml's optional ``sensor:`` section, then overrides."""
    data: dict = {}
    p = Path(path)
    if p.exists():
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        section = raw.get("sensor")
        if "sensor" in raw:
            if not isinstance(section, dict):
                raise ValueError("sensor config must be a mapping")
            data.update(section)
    data.update({k: v for k, v in overrides.items() if v is not None})
    return SensorSettings.model_validate(data)
