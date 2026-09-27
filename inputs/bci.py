"""Cortex events to step-scan selections; no classifier or stimulus ownership."""

from __future__ import annotations

import asyncio

import zmq
from pydantic import TypeAdapter, ValidationError

from inputs.scan import ScanInput
from shared.config import ScanConfig, SensorSettings
from shared.logging import get_logger
from shared.schemas import BusMessage, SensorStatus, TriggerEvent, TriggerLevel

logger = get_logger(__name__)
_adapter = TypeAdapter(BusMessage)


class BciInput(ScanInput):
    name = "bci"

    def __init__(
        self,
        *,
        config: ScanConfig | None = None,
        sensor: SensorSettings | None = None,
        context: zmq.Context | None = None,
    ) -> None:
        super().__init__(config or ScanConfig())
        self.sensor = sensor or SensorSettings()
        self.badge = {
            "emotiv": "NEXT: JAW CLENCH (MUSCLE) | SELECT: EYES CLOSED (ALPHA BAND POWER)",
            "synthetic": "SYNTHETIC SIGNAL",
            "replay": "REPLAY",
        }[self.sensor.source]
        self._context = context
        self._socket: zmq.Socket | None = None
        self._listener: asyncio.Task[None] | None = None
        self._sensor_status: SensorStatus | None = None
        self._status_received = 0.0
        self._was_ready = False
        self._ready_since = 0.0
        self._released = {"next": False, "select": False}
        self._last_level_ts = float("-inf")
        self._seen: dict[str, float] = {}
        self._last_source = {"next": float("-inf"), "select": float("-inf")}
        self._pending: list[tuple[float, TriggerEvent]] = []
        self._transport_error: str | None = None

    async def start(self) -> None:
        if self._started:
            return
        socket = (self._context or zmq.Context.instance()).socket(zmq.SUB)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVHWM, 256)
        socket.setsockopt_string(zmq.SUBSCRIBE, "")
        try:
            socket.connect(self.sensor.pub_address)
        except Exception:
            socket.close()
            raise
        self._socket = socket
        self._sensor_status = None
        self._was_ready = False
        self._transport_error = None
        self._seen.clear()
        self._last_level_ts = float("-inf")
        self._last_source = {"next": float("-inf"), "select": float("-inf")}
        await super().start()
        self._listener = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            await asyncio.gather(self._listener, return_exceptions=True)
            self._listener = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        self._sensor_status = None
        self._pending.clear()
        self._released = {"next": False, "select": False}
        await super().stop()

    async def set_targets(self, trial_id: str, labels: list[str], round: str) -> None:
        await super().set_targets(trial_id, labels, round)
        self._pending.clear()
        self._released = {"next": False, "select": False}

    def close_trial(self, reason: str = "closed") -> None:
        self._pending.clear()
        self._released = {"next": False, "select": False}
        super().close_trial(reason)

    def _fresh(self, timestamp: float, limit: float) -> bool:
        age = self.scan.wall_clock() - timestamp
        return -self.config.clock_tolerance_s <= age <= limit

    def _ready(self) -> bool:
        status = self._sensor_status
        return bool(
            self._started
            and self._transport_error is None
            and status is not None
            and status.source == self.sensor.source
            and status.connected
            and status.calibrated
            and status.armed
            and status.blocked_reason is None
            and self._fresh(status.ts, self.config.status_max_age_s)
            and self.scan.clock() - self._status_received <= self.config.status_max_age_s
        )

    def _refresh_readiness(self) -> bool:
        ready = self._ready()
        if ready != self._was_ready:
            self._pending.clear()
            self._released = {"next": False, "select": False}
            self._ready_since = self.scan.wall_clock()
            self._was_ready = ready
        return ready

    def handle_message(self, message: BusMessage) -> None:
        """Called only on the adapter event loop; diagnostic streams never select."""
        if not self._started:
            return
        self._refresh_readiness()
        if isinstance(message, SensorStatus):
            if not self._fresh(message.ts, self.config.status_max_age_s):
                return
            if self._sensor_status is not None and message.ts <= self._sensor_status.ts:
                return
            self._sensor_status, self._status_received = message, self.scan.clock()
            self._refresh_readiness()
            return
        if isinstance(message, TriggerLevel):
            if message.ts <= self._last_level_ts or not self._fresh(
                message.ts, self.config.event_max_age_s
            ):
                return
            self._last_level_ts = message.ts
            if (
                self._refresh_readiness()
                and self.scan.active()
                and message.ts >= max(self.scan.activated_at, self._ready_since)
                and self._fresh(message.ts, self.config.event_max_age_s)
            ):
                if message.next_threshold > 0 and message.next_level < message.next_threshold:
                    self._released["next"] = True
                if message.select_threshold > 0 and message.select_level < message.select_threshold:
                    self._released["select"] = True
            return
        if not isinstance(message, TriggerEvent):
            return
        now = self.scan.clock()
        self._seen = {key: expiry for key, expiry in self._seen.items() if expiry > now}
        source_time = message.source_ts + self.config.source_clock_offset_s
        if (
            message.event_id in self._seen
            or not self._fresh(message.ts, self.config.event_max_age_s)
            or not self._fresh(source_time, self.config.event_max_age_s)
            or source_time <= self._last_source[message.role]
        ):
            return
        self._seen[message.event_id] = now + self.config.event_max_age_s * 2
        self._last_source[message.role] = source_time
        if (
            not self._refresh_readiness()
            or not self.scan.active()
            or min(message.ts, source_time) < max(self.scan.activated_at, self._ready_since)
            or not self._released[message.role]
        ):
            return
        self._released[message.role] = False
        if len(self._pending) >= 256:
            self._transport_error = "trigger queue overflow"
            self.close_trial("input_overflow")
            return
        self._pending.append((now, message))

    def tick(self) -> None:
        if self._refresh_readiness() and self._pending:
            oldest = min(arrived for arrived, _ in self._pending)
            if self.scan.clock() - oldest >= self.config.coalesce_s:
                pending, self._pending = self._pending, []
                # Same completing sample: select captures the pre-next highlight.
                for _, event in sorted(
                    pending, key=lambda item: (item[1].source_ts, item[1].role != "select")
                ):
                    if not self.scan.active():
                        break
                    if not (
                        self._fresh(event.ts, self.config.event_max_age_s)
                        and self._fresh(
                            event.source_ts + self.config.source_clock_offset_s,
                            self.config.event_max_age_s,
                        )
                    ):
                        continue
                    if event.role == "next":
                        self.scan.advance()
                    else:
                        self.scan.select(
                            source=self.name, confidence=event.strength, trigger_kind=event.kind
                        )
                        logger.info(
                            "bci.selected", event_id=event.event_id, contaminated=event.contaminated
                        )
        super().tick()

    async def _listen(self) -> None:
        assert self._socket is not None
        try:
            while self._started:
                # Nonblocking bounded batches work on Windows Proactor and Unix.
                for _ in range(256):
                    try:
                        raw = self._socket.recv(flags=zmq.DONTWAIT)
                    except zmq.Again:
                        break
                    try:
                        message = _adapter.validate_json(raw)
                    except ValidationError:
                        logger.warning("bci.invalid_frame_dropped")
                        continue
                    self.handle_message(message)
                await asyncio.sleep(self.config.poll_interval_s)
        except zmq.ZMQError as exc:
            self._transport_error = str(exc)
            self._refresh_readiness()
            self.close_trial("sensor_transport_error")
            logger.error("bci.transport_failed", error=str(exc))

    def status(self) -> dict:
        ready = self._ready()
        status = self._sensor_status
        return {
            **super().status(),
            "source": self.sensor.source,
            "ready": ready,
            "connected": bool(
                self._started
                and self._transport_error is None
                and status
                and status.source == self.sensor.source
                and status.connected
                and self._fresh(status.ts, self.config.status_max_age_s)
            ),
            "badge": self.badge,
            "sensor": status.model_dump() if status else None,
            "blocked_reason": None
            if ready
            else (
                self._transport_error
                or (status.blocked_reason if status else None)
                or "waiting for fresh calibrated sensor status"
            ),
        }
