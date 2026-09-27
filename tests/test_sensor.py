"""tests/test_sensor.py — P1 trigger engine, service, recorder and replay.

Drives the engine with Cortex-shaped packets from sensor.sources.synthetic
(no headset, no sockets): next = jaw clench, select = eyes closed.
"""

from __future__ import annotations

import time

import pytest

from sensor.engine import TriggerEngine
from sensor.main import SensorService
from sensor.messages import SensorControl, TriggerEvent
from sensor.recorder import Recorder
from sensor.settings import BandTrigger, SensorSettings, load_settings
from sensor.sources.replay import read_session
from sensor.sources.synthetic import cols, packets
from sensor.triggers.base import HoldDetector

CAL = 10.0


def settings(**kw) -> SensorSettings:
    return SensorSettings(calibration_s=CAL, record=False, **kw)


def run(scenario, s: SensorSettings | None = None, contact: int = 4, engine=None):
    engine = engine or TriggerEngine(s or settings(), cols())
    out = []
    for t, p in packets(scenario, seed=1, contact=contact):
        out += engine.feed(p, t)
    return engine, [m for m in out if isinstance(m, TriggerEvent)]


def roles(events) -> list[str]:
    return [e.role for e in events]


def test_calibrates_then_stays_quiet_at_rest() -> None:
    engine, events = run([("rest", CAL + 5)])
    assert engine.calibrated
    assert events == []
    assert engine.blocked_reason(engine.last_pow_t) is None


def test_no_trigger_during_calibration() -> None:
    engine, events = run([("rest", 2), ("clench", 1), ("eyes", 3), ("rest", 2)])
    assert not engine.calibrated
    assert events == []


def test_each_clench_fires_one_next() -> None:
    sc = [("rest", CAL + 1)] + [("clench", 1.0), ("rest", 2.0)] * 3
    _, events = run(sc)
    assert roles(events) == ["next"] * 3
    assert all(e.kind == "jaw_clench" and 0 <= e.strength <= 1 for e in events)


def test_held_clench_fires_once_until_released() -> None:
    _, events = run([("rest", CAL + 1), ("clench", 5.0), ("rest", 1.0)])
    assert roles(events) == ["next"]


def test_eyes_closed_fires_select_clean() -> None:
    sc = [("rest", CAL + 1)] + [("eyes", 2.5), ("rest", 5.0)] * 2
    _, events = run(sc)
    assert roles(events) == ["select"] * 2
    assert all(e.kind == "eyes_closed" and not e.contaminated for e in events)


def test_select_own_refractory_blocks_quick_repeat() -> None:
    sc = [("rest", CAL + 1), ("eyes", 1.5), ("rest", 0.5), ("eyes", 1.5), ("rest", 4)]
    _, events = run(sc)
    assert roles(events) == ["select"]


def test_select_during_clench_is_contaminated() -> None:
    _, events = run([("rest", CAL + 1), ("both", 2.0), ("rest", 5.0)])
    sel = [e for e in events if e.role == "select"]
    assert len(sel) == 1 and sel[0].contaminated


def test_poor_contact_blocks_calibration_and_triggers() -> None:
    engine, events = run([("rest", CAL + 2), ("clench", 1), ("eyes", 3)], contact=1)
    assert not engine.calibrated and events == []


def test_gap_resets_hold() -> None:
    s = settings(
        select=BandTrigger(
            sensors=["O1", "O2"], band="alpha", z_threshold=2.0, hold_s=0.5, refractory_s=3.0
        )
    )
    engine, _ = run([("rest", CAL + 1)], s)
    start = engine.last_pow_t + 0.125
    out = []
    for t, p in packets(
        [("eyes", 0.375), ("gap", 1.0), ("eyes", 0.375), ("rest", 1)], seed=2, t0=start
    ):
        out += engine.feed(p, t)
    assert [m for m in out if isinstance(m, TriggerEvent)] == []


def test_shared_refractory_in_hold_detector() -> None:
    d = HoldDetector(threshold=1.0, hold_s=0.25, refractory_s=0.0, max_gap_s=0.5)
    fired = [d.update(t / 8, 5.0, armed=True, blocked_until=1.0).fired for t in range(6)]
    assert not any(fired)  # all samples before t=1.0 are inside the shared refractory
    fired = [d.update(1.0 + t / 8, 5.0, armed=True, blocked_until=1.0).fired for t in range(4)]
    assert fired.count(True) == 1


def test_disarmed_detector_never_fires() -> None:
    d = HoldDetector(threshold=1.0, hold_s=0.25, refractory_s=0.0, max_gap_s=0.5)
    assert not any(d.update(t / 8, 5.0, armed=False, blocked_until=0).fired for t in range(20))


def test_missing_pow_columns_raise() -> None:
    c = cols()
    c["pow"] = [x for x in c["pow"] if not x.startswith("O1/")]
    with pytest.raises(ValueError, match="O1/alpha"):
        TriggerEngine(settings(), c)


def test_settings_reject_same_feature_for_both_roles() -> None:
    same = BandTrigger(sensors=["O1"], band="alpha", z_threshold=2, hold_s=0.5, refractory_s=0)
    with pytest.raises(ValueError):
        SensorSettings(next=same, select=same)


def test_load_settings_reads_sensor_section(tmp_path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("sensor:\n  calibration_s: 12\n  min_contact_quality: 2\n", encoding="utf-8")
    s = load_settings(cfg, calibration_s=None, source="synthetic")
    assert s.calibration_s == 12 and s.min_contact_quality == 2 and s.source == "synthetic"
    assert load_settings(tmp_path / "missing.yaml").calibration_s == 20


class _Src:
    name, headset_id, connected = "synthetic", "SYNTHETIC", True


def test_service_publishes_and_recalibrates(tmp_path) -> None:
    s = settings(source="synthetic")
    sent = []
    rec = Recorder(tmp_path, 1000, label="t")
    rec.manifest(source="synthetic", headset_id="SYNTHETIC", cols=cols())
    svc = SensorService(s, _Src(), cols(), sent.append, rec)
    for t, p in packets(
        [("rest", CAL + 1), ("clench", 1), ("rest", 2), ("eyes", 2.5), ("rest", 1)],
        seed=3,
        t0=time.time(),
    ):
        svc.handle_packet(p, t)
    types = {m.type for m in sent}
    assert {"bci.bandpower", "bci.trigger_level", "bci.trigger"} <= types
    assert [m.role for m in sent if m.type == "bci.trigger"] == ["next", "select"]
    st = svc.status(svc.engine.last_pow_t)
    assert st.calibrated and st.armed and st.contact_quality["O1"] == 4

    svc.handle_control(SensorControl(ts=0, action="calibrate"), 0)
    st = svc.status(svc.engine.last_pow_t)
    assert not st.calibrated and not st.armed and st.blocked_reason == "calibrating"

    rec.close()
    manifest, pkts = read_session(rec.path)
    assert manifest["cols"]["pow"] == cols()["pow"]
    assert len(pkts) > 8 * CAL and rec.dropped == 0


def test_replayed_session_gives_same_triggers(tmp_path) -> None:
    rec = Recorder(tmp_path, 10_000, label="t")
    rec.manifest(source="synthetic", cols=cols())
    sc = [("rest", CAL + 1), ("clench", 1), ("rest", 2), ("eyes", 2.5), ("rest", 1)]
    for _, p in packets(sc, seed=4):
        rec.packet(p)
    rec.close()
    manifest, pkts = read_session(rec.path)
    engine = TriggerEngine(settings(), manifest["cols"])
    events = [m for p in pkts for m in engine.feed(p, p["time"]) if isinstance(m, TriggerEvent)]
    assert roles(events) == ["next", "select"]
