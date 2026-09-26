"""Spectator relay client (ARCHITECTURE.md section 19).

TODO: this is a stub. The real client is write-only and outbound: it
dials the relay, never accepts commands, and never lets anything that
arrives back into the pipeline. Nothing here opens a socket. link()
returns the correctly-shaped empty payload so the dashboard can hide
the QR instead of crashing on a missing field.
"""

from __future__ import annotations


class SpectatorService:
    def __init__(self, url: str = "") -> None:
        self._url = url
        self.connected_viewers = 0

    def link(self) -> dict[str, object]:
        return {"url": self._url, "connected_viewers": self.connected_viewers}

    async def publish(self, event: dict[str, object]) -> None:
        del event  # write-only once the relay exists; a stub must not invent a send
