"""Session recorder: raw Cortex packets plus published triggers, as JSONL.

Writing happens on its own thread behind a bounded queue, so a slow disk
never stalls trigger detection. When the queue is full the record is dropped
and counted (``dropped``), never blocked on. Recorded sessions stay out of git
(``data/`` is ignored).

Line kinds: ``manifest`` (first line: source, headset, Cortex columns,
settings), ``packet`` (one Cortex packet), ``event`` (a published trigger or
control message).
"""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

_STOP = object()


class Recorder:
    def __init__(self, directory: Path, queue_max: int, label: str = "sensor") -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{time.strftime('%Y%m%d-%H%M%S')}_{label}.jsonl"
        self._q: queue.Queue = queue.Queue(maxsize=queue_max)
        self.dropped = 0
        self._thread = threading.Thread(target=self._run, name="recorder", daemon=True)
        self._thread.start()

    def manifest(self, **info: object) -> None:
        self._put({"kind": "manifest", "t": time.time(), **info})

    def packet(self, packet: dict) -> None:
        self._put({"kind": "packet", "t": time.time(), "packet": packet})

    def event(self, message: dict) -> None:
        self._put({"kind": "event", "t": time.time(), "message": message})

    def _put(self, rec: object) -> None:
        try:
            self._q.put_nowait(rec)
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            while True:
                rec = self._q.get()
                if rec is _STOP:
                    return
                f.write(json.dumps(rec, default=str) + "\n")
                if self._q.empty():
                    f.flush()

    def close(self, timeout: float = 5.0) -> None:
        try:
            self._q.put(_STOP, timeout=timeout)
        except queue.Full:
            return
        self._thread.join(timeout)
