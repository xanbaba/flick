"""Live Emotiv source: Cortex pow, dev, eq and fac streams.

No training profile is loaded: both triggers are read from band power.
"""

from __future__ import annotations

from sensor.sources.base import STREAMS, OnPacket
from sensor.sources.cortex_client import CortexClient
from shared.logging import get_logger

log = get_logger(__name__)


class CortexSource:
    name = "emotiv"

    def __init__(
        self, client_id: str, client_secret: str, url: str, headset_id: str | None = None
    ) -> None:
        if not client_id or not client_secret:
            raise RuntimeError("EMOTIV_CLIENT_ID / EMOTIV_CLIENT_SECRET are not set in .env")
        self._wanted_headset = headset_id
        self._client = CortexClient(
            client_id, client_secret, url, log=lambda m: log.info("cortex", msg=m)
        )
        self.headset_id: str | None = None
        self.connected = False

    def start(self, on_packet: OnPacket) -> dict[str, list]:
        self._client.on_data = on_packet
        self._client.connect()
        cols = self._client.start(STREAMS, headset_id=self._wanted_headset)
        self.headset_id = self._client.headset_id
        self.connected = True
        return cols

    def close(self) -> None:
        self.connected = False
        self._client.close()
