"""tests/test_schemas.py — the contract everything else depends on.

Round-trips every model in shared/schemas.py, asserts every required
field is actually enforced, and asserts the discriminated union on
"type" resolves to the correct concrete model.
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from shared.schemas import (
    BusMessage,
    ClientMessage,
    EegChunk,
    GraphEdge,
    GraphNode,
    KeyPress,
    PsdFrame,
    RequestSnapshot,
    Selection,
    SensorSelection,
    SensorStatus,
    ShowTargets,
    StimControl,
    StimulusIntegrity,
    StimulusOnset,
    StimulusProfile,
    TargetScores,
)

# One valid set of kwargs per model in section 6. Every model here
# must exist with exactly these field names and types.
VALID_KWARGS: dict[type[BaseModel], dict] = {
    Selection: dict(
        type="input.selection",
        ts=1.0,
        trial_id="trial-1",
        target_idx=0,
        confidence=0.9,
        source="keyboard",
        algorithm=None,
    ),
    EegChunk: dict(
        type="bci.eeg",
        ts=1.0,
        fs=250,
        channels=["O1", "Oz"],
        data=[[1.0, 2.0], [3.0, 4.0]],
        railed=[False, False],
    ),
    PsdFrame: dict(
        type="bci.psd",
        ts=1.0,
        freqs=[0.0, 0.5],
        power=[-10.0, -9.0],
        peaks=[-10.0],
    ),
    TargetScores: dict(
        type="bci.scores",
        ts=1.0,
        algorithm="fbcca",
        rho=[0.1, 0.2],
        winner_idx=1,
        margin=1.2,
        above_threshold=False,
        dwell_count=0,
    ),
    SensorSelection: dict(
        type="bci.selection",
        ts=1.0,
        trial_id="trial-1",
        target_idx=1,
        rho=0.62,
        margin=1.8,
        algorithm="fbcca",
    ),
    SensorStatus: dict(
        type="bci.status",
        ts=1.0,
        source="synthetic",
        connected=True,
        configured=True,
        samples_received=100,
        dropped_samples=0,
        railed_channels=[],
    ),
    KeyPress: dict(
        type="client.key_press",
        ts=1.0,
        key="3",
    ),
    RequestSnapshot: dict(
        type="client.request_snapshot",
        ts=1.0,
    ),
    ShowTargets: dict(
        type="stim.show_targets",
        ts=1.0,
        trial_id="trial-1",
        labels=["a", "b"],
        round="intent",
        cue_idx=None,
    ),
    StimControl: dict(
        type="stim.control",
        ts=1.0,
        action="idle",
        message=None,
    ),
    StimulusProfile: dict(
        type="stim.profile",
        ts=1.0,
        profile="hi",
        measured_refresh_hz=144.0,
        frequencies=[8.0, 9.6],
        phases=[0.0, 1.5707963],
        cancel_idx=4,
        window_s=1.25,
        bandpass_low_hz=6.0,
        fbcca_subband_low_hz=[6.0, 14.0],
    ),
    StimulusOnset: dict(
        type="stim.onset",
        ts=1.0,
        trial_id="trial-1",
        frequencies=[8.0],
    ),
    StimulusIntegrity: dict(
        type="stim.integrity",
        ts=1.0,
        measured_refresh_hz=144.0,
        dropped_frames_last_s=0,
        frame_interval_std_ms=0.2,
    ),
    GraphNode: dict(
        id="n1",
        label="Sofia",
        kind="Person",
        weight=1.0,
        last_accessed=1.0,
    ),
    GraphEdge: dict(
        id="e1",
        source="n1",
        target="n2",
        kind="KNOWS",
        weight=1.0,
    ),
}

MODEL_CASES = list(VALID_KWARGS.items())
MODEL_IDS = [cls.__name__ for cls, _ in MODEL_CASES]

# Models that carry "type" and "ts" and participate in the discriminated
# BusMessage union: the ZMQ bus (section 6.1, 6.2, 6.4, 6.5).
BUS_MESSAGE_MODELS = [
    Selection,
    EegChunk,
    PsdFrame,
    TargetScores,
    SensorSelection,
    SensorStatus,
    ShowTargets,
    StimControl,
    StimulusProfile,
    StimulusOnset,
    StimulusIntegrity,
]

# Models that carry "type" and "ts" and participate in the discriminated
# ClientMessage union: the inbound WebSocket channel (section 6.3).
CLIENT_MESSAGE_MODELS = [
    KeyPress,
    RequestSnapshot,
]

BUS_ADAPTER: TypeAdapter[BusMessage] = TypeAdapter(BusMessage)
CLIENT_ADAPTER: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


@pytest.mark.parametrize("model_cls,kwargs", MODEL_CASES, ids=MODEL_IDS)
def test_round_trip(model_cls: type[BaseModel], kwargs: dict) -> None:
    """Every model survives a dump-and-reload through both JSON and dict."""
    instance = model_cls.model_validate(kwargs)
    restored_from_json = model_cls.model_validate_json(instance.model_dump_json())
    restored_from_dict = model_cls.model_validate(instance.model_dump())
    assert restored_from_json == instance
    assert restored_from_dict == instance


@pytest.mark.parametrize("model_cls,kwargs", MODEL_CASES, ids=MODEL_IDS)
def test_required_fields_are_enforced(model_cls: type[BaseModel], kwargs: dict) -> None:
    """Dropping any required field must fail validation."""
    required_fields = [name for name, info in model_cls.model_fields.items() if info.is_required()]
    assert required_fields, f"{model_cls.__name__} has no required fields to test"

    for field_name in required_fields:
        incomplete = {k: v for k, v in kwargs.items() if k != field_name}
        with pytest.raises(ValidationError):
            model_cls.model_validate(incomplete)


@pytest.mark.parametrize(
    "model_cls", BUS_MESSAGE_MODELS, ids=[m.__name__ for m in BUS_MESSAGE_MODELS]
)
def test_every_bus_message_carries_type_and_ts(model_cls: type[BaseModel]) -> None:
    assert "type" in model_cls.model_fields
    assert "ts" in model_cls.model_fields


@pytest.mark.parametrize(
    "model_cls", BUS_MESSAGE_MODELS, ids=[m.__name__ for m in BUS_MESSAGE_MODELS]
)
def test_discriminated_union_resolves_to_the_correct_model(model_cls: type[BaseModel]) -> None:
    instance = model_cls.model_validate(VALID_KWARGS[model_cls])
    resolved = BUS_ADAPTER.validate_json(instance.model_dump_json())
    assert type(resolved) is model_cls
    assert resolved == instance


def test_discriminated_union_rejects_an_unknown_type() -> None:
    with pytest.raises(ValidationError):
        BUS_ADAPTER.validate_python({"type": "not.a.real.type", "ts": time.time()})


@pytest.mark.parametrize(
    "model_cls", CLIENT_MESSAGE_MODELS, ids=[m.__name__ for m in CLIENT_MESSAGE_MODELS]
)
def test_every_client_message_carries_type_and_ts(model_cls: type[BaseModel]) -> None:
    assert "type" in model_cls.model_fields
    assert "ts" in model_cls.model_fields


@pytest.mark.parametrize(
    "model_cls", CLIENT_MESSAGE_MODELS, ids=[m.__name__ for m in CLIENT_MESSAGE_MODELS]
)
def test_client_message_union_resolves_to_the_correct_model(model_cls: type[BaseModel]) -> None:
    instance = model_cls.model_validate(VALID_KWARGS[model_cls])
    resolved = CLIENT_ADAPTER.validate_json(instance.model_dump_json())
    assert type(resolved) is model_cls
    assert resolved == instance


def test_client_message_union_rejects_an_unknown_type() -> None:
    with pytest.raises(ValidationError):
        CLIENT_ADAPTER.validate_python({"type": "not.a.real.type", "ts": time.time()})


def test_bus_and_client_unions_do_not_overlap() -> None:
    """KeyPress/RequestSnapshot are WS-inbound, not ZMQ bus messages,
    and vice versa: the two discriminated unions are disjoint."""
    assert not set(CLIENT_MESSAGE_MODELS) & set(BUS_MESSAGE_MODELS)


def test_graph_node_and_edge_are_ws_payload_objects_not_bus_messages() -> None:
    """GraphNode/GraphEdge (section 6.7) carry no type field: they are
    WebSocket payload sub-objects, not top-level ZMQ bus messages."""
    assert "type" not in GraphNode.model_fields
    assert "type" not in GraphEdge.model_fields
    assert GraphNode not in BUS_MESSAGE_MODELS
    assert GraphEdge not in BUS_MESSAGE_MODELS
