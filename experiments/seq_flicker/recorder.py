"""Writes a session folder: meta.json, events.csv and one CSV per stream."""

from __future__ import annotations

import csv
import json
import threading
from pathlib import Path

EVENT_FIELDS = [
    "t_wall",
    "block",
    "phase",
    "target",
    "active_tile",
    "flicker_all",
    "cycle",
    "slot_pos",
    "planned_s",
    "actual_s",
    "frames",
    "dropped_frames",
]


def _flatten_cols(cols: list) -> list[str]:
    out: list[str] = []
    for c in cols:
        if isinstance(c, list):
            out.extend(f"cq_{x}" for x in c)
        else:
            out.append(str(c))
    return out


def _flatten_row(values: list) -> list:
    out: list = []
    for v in values:
        if isinstance(v, list):
            out.extend(v)
        else:
            out.append(v)
    return out


class Recorder:
    def __init__(self, folder: Path, cols: dict[str, list], meta: dict) -> None:
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._files = {}
        self._writers = {}
        for stream, c in cols.items():
            f = open(folder / f"{stream}.csv", "w", newline="", encoding="utf-8")  # noqa: SIM115
            w = csv.writer(f)
            w.writerow(["t"] + _flatten_cols(c))
            self._files[stream], self._writers[stream] = f, w
        f = open(folder / "events.csv", "w", newline="", encoding="utf-8")  # noqa: SIM115
        self._files["events"] = f
        self._events = csv.DictWriter(f, fieldnames=EVENT_FIELDS)
        self._events.writeheader()
        self.meta = meta
        self.write_meta()
        self.samples = {s: 0 for s in cols}
        self.latest: dict[str, dict] = {}

    def write_meta(self) -> None:
        (self.folder / "meta.json").write_text(json.dumps(self.meta, indent=2), encoding="utf-8")

    def on_data(self, data: dict) -> None:
        """Cortex data callback. Runs on the websocket thread."""
        with self._lock:
            for stream, w in self._writers.items():
                if stream in data:
                    w.writerow([data["time"]] + _flatten_row(data[stream]))
                    self.samples[stream] += 1
                    self.latest[stream] = data

    def event(self, **row) -> None:
        with self._lock:
            self._events.writerow({k: row.get(k) for k in EVENT_FIELDS})

    def close(self) -> None:
        with self._lock:
            for f in self._files.values():
                f.close()
        self.write_meta()
