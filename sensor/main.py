"""P1 sensor process (ARCHITECTURE.md §8): ``python -m sensor.main``.

Reads the headset (or a synthetic / replayed source), calibrates on 20 s of
relaxed, eyes-open data, then publishes on ZMQ 5555:

* ``bci.bandpower``      every Cortex pow sample (8 Hz)
* ``bci.trigger_level``  every pow sample once calibrated (z-scores)
* ``bci.trigger``        ``next`` = jaw clench, ``select`` = eyes closed ~2 s
* ``bci.status``         1 Hz: connection, contact, calibration, armed/blocked

It listens on 5556 for ``sensor.control`` ``{"action": "calibrate"}`` to redo
the calibration. P1 never adds tile or trial IDs: the backend decides what a
trigger means.
"""

from __future__ import annotations

import argparse
import queue
import time

import zmq

from sensor.engine import TriggerEngine
from sensor.messages import BandPowerFrame, SensorControl, SensorStatus
from sensor.recorder import Recorder
from sensor.settings import SensorSettings, load_settings
from sensor.sources.base import Source
from shared.config import EnvSettings
from shared.logging import configure_logging, get_logger

log = get_logger(__name__)


def make_source(s: SensorSettings) -> Source:
    if s.source == "synthetic":
        from sensor.sources.synthetic import SyntheticSource, default_scenario

        return SyntheticSource(default_scenario(s.calibration_s))
    if s.source == "replay":
        if not s.replay_file:
            raise SystemExit("--replay-file is required with --source replay")
        from sensor.sources.replay import ReplaySource

        return ReplaySource(s.replay_file)
    from sensor.sources.cortex import CortexSource

    env = EnvSettings()
    return CortexSource(env.emotiv_client_id, env.emotiv_client_secret, s.cortex_url, s.headset_id)


class SensorService:
    """Glue between a source, the engine, the recorder and the bus.

    ``handle_packet`` / ``status`` / ``handle_control`` are plain methods so
    tests can drive the service without sockets or threads.
    """

    def __init__(
        self,
        settings: SensorSettings,
        source: Source,
        cols: dict[str, list],
        publish,
        recorder: Recorder | None = None,
    ) -> None:
        self.s = settings
        self.source = source
        self.cols = cols
        self.publish = publish
        self.recorder = recorder
        self.engine = TriggerEngine(settings, cols)
        self.engine.start_calibration(None)

    def handle_packet(self, packet: dict, now: float) -> None:
        if self.recorder:
            self.recorder.packet(packet)
        if "pow" in packet:
            try:
                power = self.engine.bandpower_matrix(packet["pow"])
                self.publish(
                    BandPowerFrame(
                        ts=now,
                        sensors=self.engine.pow_sensors,
                        bands=self.engine.pow_bands,
                        power=power,
                    )
                )
            except (TypeError, ValueError, IndexError):
                pass
        was_calibrated = self.engine.calibrated
        for msg in self.engine.feed(packet, now):
            self.publish(msg)
            if msg.type == "bci.trigger":
                log.info(
                    "trigger",
                    role=msg.role,
                    kind=msg.kind,
                    strength=round(msg.strength, 2),
                    contaminated=msg.contaminated,
                )
                if self.recorder:
                    self.recorder.event(msg.model_dump())
        if self.engine.calibrated and not was_calibrated:
            log.info(
                "calibrated",
                next_mean=round(self.engine.b_next.mean, 3),
                next_sd=round(self.engine.b_next.sd, 3),
                select_mean=round(self.engine.b_select.mean, 3),
                select_sd=round(self.engine.b_select.sd, 3),
            )
            if self.recorder:
                self.recorder.event(
                    {
                        "type": "calibrated",
                        "next": [self.engine.b_next.mean, self.engine.b_next.sd],
                        "select": [self.engine.b_select.mean, self.engine.b_select.sd],
                    }
                )

    def handle_control(self, ctl: SensorControl, now: float) -> None:
        if ctl.action == "calibrate":
            log.info("recalibrating")
            self.engine.start_calibration(None)
        else:
            log.warning("control action not supported", action=ctl.action)
        if self.recorder:
            self.recorder.event(ctl.model_dump())

    def status(self, now: float) -> SensorStatus:
        e = self.engine
        reason = e.blocked_reason(now if self.s.source == "emotiv" else (e.last_pow_t or now))
        return SensorStatus(
            ts=now,
            source=self.s.source,
            connected=self.source.connected,
            headset_id=self.source.headset_id,
            battery_pct=e.battery,
            contact_quality=e.contact,
            eeg_quality=e.eeg_quality,
            streams=sorted(self.cols),
            calibrated=e.calibrated,
            calibration_progress=round(e.calibration_progress, 3),
            armed=reason is None,
            blocked_reason=reason,
            dropped_samples=self.recorder.dropped if self.recorder else 0,
        )


def run(settings: SensorSettings) -> None:
    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.bind(settings.pub_address)
    ctl = ctx.socket(zmq.SUB)
    ctl.connect(settings.control_address)
    ctl.setsockopt_string(zmq.SUBSCRIBE, "")

    def publish(msg) -> None:
        pub.send_string(msg.model_dump_json())

    packets: queue.Queue = queue.Queue(maxsize=5000)
    dropped_in = 0

    def on_packet(p: dict) -> None:
        nonlocal dropped_in
        try:
            packets.put_nowait(p)
        except queue.Full:
            dropped_in += 1

    # Connect to the headset first: nothing else is worth starting without it.
    source = make_source(settings)
    log.info("starting source", source=settings.source)
    cols = source.start(on_packet)
    log.info("source ready", headset=source.headset_id, streams=sorted(cols))

    recorder = None
    if settings.record:
        recorder = Recorder(
            settings.record_dir, settings.record_queue_max, label=f"sensor_{settings.source}"
        )
        recorder.manifest(
            source=settings.source,
            headset_id=source.headset_id,
            cols=cols,
            settings=settings.model_dump(mode="json"),
        )
        log.info("recording", path=str(recorder.path))

    svc = SensorService(settings, source, cols, publish, recorder)
    log.info("calibrating: sit still, eyes open, relaxed jaw", seconds=settings.calibration_s)
    next_status = 0.0
    try:
        while True:
            try:
                p = packets.get(timeout=0.05)
                svc.handle_packet(p, time.time())
            except queue.Empty:
                pass
            while ctl.poll(0):
                raw = ctl.recv_string()
                if '"sensor.control"' in raw:
                    try:
                        svc.handle_control(SensorControl.model_validate_json(raw), time.time())
                    except ValueError as exc:
                        log.warning("bad control message", error=str(exc))
            now = time.time()
            if now >= next_status:
                st = svc.status(now)
                st.dropped_samples += dropped_in
                publish(st)
                next_status = now + 1.0 / settings.status_hz
            if settings.source == "replay" and not source.connected and packets.empty():
                log.info("replay finished")
                break
    except KeyboardInterrupt:
        log.info("stopping")
    finally:
        source.close()
        if recorder:
            recorder.close()
        pub.close(linger=0)
        ctl.close(linger=0)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m sensor.main", description=__doc__.split("\n")[0])
    ap.add_argument("--source", choices=["emotiv", "synthetic", "replay"])
    ap.add_argument("--replay-file")
    ap.add_argument("--calibration-s", type=float)
    ap.add_argument("--headset-id")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--config", default="config.yaml")
    a = ap.parse_args(argv)
    configure_logging(log_file="sensor.log")
    settings = load_settings(
        a.config,
        source=a.source,
        replay_file=a.replay_file,
        calibration_s=a.calibration_s,
        headset_id=a.headset_id,
        record=False if a.no_record else None,
    )
    run(settings)


if __name__ == "__main__":
    main()
