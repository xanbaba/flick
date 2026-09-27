"""WebSocket hub (ARCHITECTURE.md sections 6.3 and 6.6).

Outbound messages use the envelope {"type", "ts", "payload"}. Inbound
traffic is only the client.* channel: a key press is forwarded to the
active input adapter, and a snapshot request is answered with
graph.snapshot plus one sys.status. Anything that fails validation is
logged and dropped, never raised to the caller.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from inputs.base import InputSource
from shared.bus import Subscriber
from shared.logging import get_logger
from shared.schemas import (
    ClientMessage,
    EegChunk,
    KeyPress,
    PsdFrame,
    RequestSnapshot,
    TargetScores,
)

logger = get_logger(__name__)

_client_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)

SnapshotFn = Callable[[], Awaitable[dict[str, object]]]
StatusFn = Callable[[], dict[str, object]]


class Hub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message_type: str, payload: dict[str, object]) -> None:
        body = {"type": message_type, "ts": time.time(), "payload": payload}
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_json(body)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def send(self, ws: WebSocket, message_type: str, payload: dict[str, object]) -> None:
        await ws.send_json({"type": message_type, "ts": time.time(), "payload": payload})


async def relay_sensor(hub: Hub, address: str) -> None:
    """Rebroadcast P1's bci.eeg / bci.psd / bci.scores onto the dashboard socket.

    SUB connect does not require the sensor to be up. Frames that are
    not one of those three types (status, selections, stimulus) are
    ignored here; status is assembled by the app's own 1 Hz loop.
    """
    subscriber = Subscriber(address)
    try:
        while True:
            if subscriber.poll(50):
                try:
                    message = subscriber.recv()
                except ValidationError:
                    logger.warning("ws.malformed_sensor_frame_dropped")
                    continue
                if isinstance(message, EegChunk):
                    await hub.broadcast(
                        "eeg.trace",
                        {"channels": message.channels, "data": message.data, "fs": message.fs},
                    )
                elif isinstance(message, PsdFrame):
                    await hub.broadcast(
                        "eeg.psd",
                        {"freqs": message.freqs, "power": message.power, "peaks": message.peaks},
                    )
                elif isinstance(message, TargetScores):
                    await hub.broadcast("bci.scores", message.model_dump())
            else:
                await asyncio.sleep(0)
    finally:
        subscriber.close()


async def serve(
    ws: WebSocket,
    *,
    hub: Hub,
    input_source: Callable[[], InputSource],
    snapshot: SnapshotFn,
    status: StatusFn,
    on_connect: Callable[[], list[tuple[str, dict[str, object]]]] | None = None,
) -> None:
    await hub.connect(ws)
    try:
        await hub.send(ws, "graph.snapshot", await snapshot())
        await hub.send(ws, "sys.status", status())
        for message_type, payload in on_connect() if on_connect is not None else []:
            await hub.send(ws, message_type, payload)
        while True:
            raw = await ws.receive_text()
            await _handle_inbound(raw, ws, hub, input_source, snapshot, status)
    except WebSocketDisconnect:
        logger.debug("ws.disconnected")
    finally:
        hub.disconnect(ws)


async def _handle_inbound(
    raw: str,
    ws: WebSocket,
    hub: Hub,
    input_source: Callable[[], InputSource],
    snapshot: SnapshotFn,
    status: StatusFn,
) -> None:
    try:
        message = _client_adapter.validate_json(raw)
    except ValidationError:
        logger.warning("ws.invalid_inbound_dropped")
        return
    if isinstance(message, KeyPress):
        source = input_source()
        handler = getattr(source, "handle_key_press", None)
        if handler is not None:
            handler(message)
        return
    if isinstance(message, RequestSnapshot):
        await hub.send(ws, "graph.snapshot", await snapshot())
        await hub.send(ws, "sys.status", status())
