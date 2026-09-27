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
import uuid
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
    PlaybackComplete,
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
        self._playbacks: dict[str, dict[WebSocket, asyncio.Future[str]]] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        for pending in self._playbacks.values():
            future = pending.get(ws)
            if future is not None and not future.done():
                future.set_result("unconfirmed")

    def playback_complete(self, ws: WebSocket, message: PlaybackComplete) -> None:
        future = self._playbacks.get(message.playback_id, {}).get(ws)
        if future is not None and not future.done():
            future.set_result(message.outcome)

    async def play(self, payload: dict[str, object], timeout_s: float) -> str:
        """Wait for every recipient; a silent or disconnected client is not completion."""
        playback_id = uuid.uuid4().hex
        pending = {ws: asyncio.get_running_loop().create_future() for ws in self._clients}
        self._playbacks[playback_id] = pending
        try:
            await self.broadcast(
                "conv.spoken",
                {**payload, "playback_id": playback_id, "playback_timeout_s": timeout_s},
            )
            if not pending:
                return "unavailable"
            try:
                outcomes = await asyncio.wait_for(asyncio.gather(*pending.values()), timeout_s)
            except TimeoutError:
                return "unconfirmed"
            if "unconfirmed" in outcomes:
                return "unconfirmed"
            return "completed" if all(result == "completed" for result in outcomes) else "failed"
        finally:
            self._playbacks.pop(playback_id, None)

    async def broadcast(self, message_type: str, payload: dict[str, object]) -> None:
        body = {"type": message_type, "ts": time.time(), "payload": payload}
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_json(body)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

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
            # Non-blocking poll: a blocking poll here stalls the whole event
            # loop (every WS send and the BCI input's 20 ms polling).
            if subscriber.poll(0):
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
                await asyncio.sleep(0.02)
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
        await _send_snapshot(ws, hub, snapshot)
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
        await _send_snapshot(ws, hub, snapshot)
        await hub.send(ws, "sys.status", status())
    elif isinstance(message, PlaybackComplete):
        hub.playback_complete(ws, message)


async def _send_snapshot(ws: WebSocket, hub: Hub, snapshot: SnapshotFn) -> None:
    from backend.app.services.tiger import MemoryUnavailableError

    try:
        payload = await snapshot()
    except MemoryUnavailableError:
        # The following sys.status describes the error. Never fabricate an empty graph.
        return
    await hub.send(ws, "graph.snapshot", payload)
