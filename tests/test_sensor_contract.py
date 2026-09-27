"""Sensor output must survive the shared wire contract without losing identity."""

from __future__ import annotations

import re
import time
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
import zmq
from pydantic import ValidationError

from sensor import messages
from sensor.main import SensorService
from sensor.settings import SensorSettings, load_settings
from sensor.sources.synthetic import cols, packets
from shared.bus import Subscriber, _bus_adapter
from shared.config import load_config
from shared.schemas import BandPowerFrame, SensorControl, SensorStatus, TriggerEvent, TriggerLevel

ROOT = Path(__file__).resolve().parents[1]
MODELS = [BandPowerFrame, TriggerLevel, TriggerEvent, SensorStatus, SensorControl]


class SyntheticSource:
    name = "synthetic"
    headset_id = "SYNTHETIC"
    connected = True


def test_sensor_service_messages_cross_shared_subscriber() -> None:
    sent = []
    service = SensorService(
        SensorSettings(source="synthetic", calibration_s=6, record=False),
        SyntheticSource(),
        cols(),
        sent.append,
    )
    for timestamp, packet in packets(
        [("rest", 8), ("clench", 1), ("rest", 2), ("eyes", 3)], t0=time.time(), seed=3
    ):
        service.handle_packet(packet, timestamp)
    triggers = [message for message in sent if isinstance(message, TriggerEvent)]
    assert [message.role for message in triggers] == ["next", "select"]
    assert len({message.event_id for message in triggers}) == len(triggers)
    # One of each diagnostic plus both actual detector events and readiness.
    samples = [next(message for message in sent if isinstance(message, cls)) for cls in MODELS[:2]]
    samples += triggers + [
        service.status(timestamp),
        SensorControl(ts=timestamp, action="calibrate"),
    ]
    context = zmq.Context()
    publisher = context.socket(zmq.XPUB)
    address = f"inproc://sensor-contract-{uuid4()}"
    publisher.bind(address)
    subscriber = Subscriber(address, context=context)
    try:
        # XPUB confirms subscription deterministically, avoiding a slow-joiner sleep.
        assert publisher.poll(1000)
        assert publisher.recv() == b"\x01"
        for message in samples:
            publisher.send_string(message.model_dump_json())
            assert subscriber.poll(1000)
            restored = subscriber.recv()
            assert type(restored) is type(message)
            assert restored.model_dump() == message.model_dump()
        event = triggers[0]
        assert _bus_adapter.validate_json(event.model_dump_json()).event_id == event.event_id
    finally:
        subscriber.close()
        publisher.close(linger=0)
        context.term()


@pytest.mark.parametrize("model", MODELS)
def test_sensor_imports_and_typescript_fields_match_shared_contract(model: type) -> None:
    assert getattr(messages, model.__name__) is model
    typescript = (ROOT / "frontend/src/lib/types.ts").read_text(encoding="utf-8")
    body = re.search(rf"export interface {model.__name__} \{{(.*?)\n\}}", typescript, re.S)
    assert body is not None
    fields = set(re.findall(r"\b(\w+)\s*:", re.sub(r"//[^\n]*", "", body[1])))
    assert fields == set(model.model_fields)


@pytest.mark.parametrize(
    "change",
    [
        {"event_id": ""},
        {"event_id": None},
        {"role": "next", "kind": "eyes_closed"},
        {"role": "select", "kind": "jaw_clench"},
        {"strength": 1.1},
        {"strength": -0.1},
        {"ts": float("nan")},
        {"source_ts": float("inf")},
    ],
)
def test_invalid_triggers_rejected_on_bus(change: dict) -> None:
    message = dict(
        type="bci.trigger",
        ts=1.0,
        source_ts=0.9,
        event_id="event-1",
        role="next",
        kind="jaw_clench",
        strength=0.8,
    )
    message.update(change)
    with pytest.raises(ValidationError):
        _bus_adapter.validate_python(message)


def test_missing_identity_is_not_invented_by_consumer() -> None:
    with pytest.raises(ValidationError):
        _bus_adapter.validate_python(
            dict(
                type="bci.trigger",
                ts=1.0,
                source_ts=0.9,
                role="next",
                kind="jaw_clench",
                strength=0.8,
            )
        )


def test_status_preserves_live_fields_without_inventing_legacy_measurements() -> None:
    message = SensorStatus(
        ts=1,
        source="emotiv",
        connected=True,
        headset_id="test",
        calibrated=True,
        calibration_progress=1,
        armed=True,
    )
    decoded = _bus_adapter.validate_json(message.model_dump_json())
    assert decoded.headset_id == "test" and decoded.calibrated and decoded.armed
    assert decoded.samples_received is None and decoded.railed_channels is None
    legacy = _bus_adapter.validate_python(
        dict(
            type="bci.status",
            ts=1,
            source="cyton",
            connected=True,
            configured=True,
            samples_received=100,
            dropped_samples=0,
            railed_channels=[],
        )
    )
    assert not legacy.calibrated and not legacy.armed
    assert legacy.samples_received == 100


def test_unimplemented_training_control_rejected() -> None:
    with pytest.raises(ValidationError):
        _bus_adapter.validate_python(dict(type="sensor.control", ts=1, action="train"))


def test_both_loaders_use_runtime_sensor_config(tmp_path: Path) -> None:
    path = ROOT / "config.yaml"
    app = load_config(path)
    assert app.sensor == load_settings(path)
    assert app.sensor.source == "emotiv" and app.sensor.record is False
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["sensor"]["next"]["z_threshold"] = 9.5
    raw["sensor"]["calibration_s"] = 12
    custom = tmp_path / "config.yaml"
    custom.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert load_config(custom).sensor == load_settings(custom)
    assert load_settings(custom).next.z_threshold == 9.5
    assert load_settings(custom, calibration_s=15).calibration_s == 15


@pytest.mark.parametrize(
    "sensor",
    [
        {"calibration_s": float("inf")},
        {"max_sample_gap_s": float("nan")},
        {"status_hz": 0},
        {"min_contact_quality": 5},
        {"min_calibration_fraction": 1.1},
        {"next": dict(sensors=[], band="gamma", z_threshold=8, hold_s=0.25, refractory_s=0)},
        "not a mapping",
        None,
    ],
)
def test_invalid_sensor_settings_rejected_by_both_loaders(tmp_path: Path, sensor: object) -> None:
    raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    raw["sensor"] = sensor
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    for loader in (load_settings, load_config):
        with pytest.raises(ValueError):
            loader(path)
