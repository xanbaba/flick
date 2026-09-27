"""Replays a recorded session (``data/sessions/*.jsonl``) at its original pace."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from sensor.sources.base import OnPacket


def read_session(path: Path | str) -> tuple[dict, list[dict]]:
    manifest: dict = {}
    pkts: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("kind") == "manifest":
                manifest = rec
            elif rec.get("kind") == "packet":
                pkts.append(rec["packet"])
    if not manifest.get("cols"):
        raise ValueError(f"{path}: no manifest with Cortex columns")
    return manifest, pkts


class ReplaySource:
    name = "replay"

    def __init__(self, path: Path | str, speed: float = 1.0) -> None:
        self.manifest, self.packets = read_session(path)
        self.speed = speed
        self.headset_id = self.manifest.get("headset_id")
        self.connected = False
        self._stop = threading.Event()

    def start(self, on_packet: OnPacket) -> dict[str, list]:
        def run() -> None:
            if not self.packets:
                return
            t_first = float(self.packets[0].get("time", 0.0))
            wall0 = time.time()
            for p in self.packets:
                due = wall0 + (float(p.get("time", t_first)) - t_first) / self.speed
                delay = due - time.time()
                if delay > 0 and self._stop.wait(delay):
                    return
                on_packet(p)
            self.connected = False

        self.connected = True
        threading.Thread(target=run, name="replay-source", daemon=True).start()
        return self.manifest["cols"]

    def close(self) -> None:
        self._stop.set()
        self.connected = False
