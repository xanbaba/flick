"""What every P1 data source provides.

A source delivers Cortex-shaped packets (``{"pow": [...], "time": t}``,
``{"dev": [...], "time": t}``, ...) to ``on_packet`` from its own thread, and
reports the subscribe columns from ``start()``. The engine never knows which
source it is reading.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

Packet = dict
OnPacket = Callable[[Packet], None]

STREAMS = ["pow", "dev", "eq", "fac"]


class Source(Protocol):
    name: str
    headset_id: str | None
    connected: bool

    def start(self, on_packet: OnPacket) -> dict[str, list]: ...

    def close(self) -> None: ...
