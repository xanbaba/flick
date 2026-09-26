"""Thin ZMQ PUB/SUB wrappers, typed against shared.schemas.

Every message is a pydantic model with a ``type`` field; on the wire
it is a single JSON string frame. Nothing here does filtering by ZMQ
topic prefix — subscribers decode every frame and dispatch on
``type`` because ZMQ topic filtering on raw bytes is a needless
second layer on top of a field we already validate.
"""

from __future__ import annotations

from typing import TypeVar

import zmq
from pydantic import BaseModel, TypeAdapter

from shared.schemas import BusMessage

T = TypeVar("T", bound=BaseModel)

_bus_adapter: TypeAdapter[BusMessage] = TypeAdapter(BusMessage)


class Publisher:
    """Binds a ZMQ PUB socket and sends pydantic models as JSON frames."""

    def __init__(self, address: str, *, context: zmq.Context | None = None) -> None:
        self._context = context or zmq.Context.instance()
        self._socket = self._context.socket(zmq.PUB)
        self._socket.bind(address)

    def send(self, message: BaseModel) -> None:
        self._socket.send_string(message.model_dump_json())

    def close(self) -> None:
        self._socket.close()

    def __enter__(self) -> Publisher:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class Subscriber:
    """Connects a ZMQ SUB socket and decodes JSON frames into models."""

    def __init__(self, address: str, *, context: zmq.Context | None = None) -> None:
        self._context = context or zmq.Context.instance()
        self._socket = self._context.socket(zmq.SUB)
        self._socket.connect(address)
        self._socket.setsockopt_string(zmq.SUBSCRIBE, "")

    def recv(self, *, flags: int = 0) -> BusMessage:
        """Block for the next frame and decode it against the bus union."""
        raw = self._socket.recv_string(flags)
        return _bus_adapter.validate_json(raw)

    def recv_as(self, model: type[T], *, flags: int = 0) -> T:
        """Block for the next frame and decode it as a specific model."""
        raw = self._socket.recv_string(flags)
        return model.model_validate_json(raw)

    def poll(self, timeout_ms: int = 0) -> bool:
        """Return True if a frame is available within timeout_ms."""
        return bool(self._socket.poll(timeout_ms, zmq.POLLIN))

    def close(self) -> None:
        self._socket.close()

    def __enter__(self) -> Subscriber:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
