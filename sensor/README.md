# P1 sensor (Dev B)

`python -m sensor.main` — reads the Emotiv EPOC X through Cortex and publishes
triggers on ZMQ `tcp://127.0.0.1:5555` (ARCHITECTURE.md §8).

| Role   | Action                 | Signal (Cortex `pow`)                         | Rule                                  |
|--------|------------------------|-----------------------------------------------|---------------------------------------|
| next   | jaw clench             | mean log10 gamma, FC5 FC6 T7 T8               | z ≥ 8 held 0.25 s                     |
| select | eyes closed about 2 s  | mean log10 alpha, O1 O2                       | z ≥ 2 held 0.5 s, 3 s own refractory  |

Both z-scores are against a 20 s eyes-open, relaxed calibration that runs at
start-up (and again on `sensor.control {"action": "calibrate"}` from 5556).
Shared 0.8 s refractory between roles, release before re-arming, a data gap
over 0.5 s resets any hold, and nothing fires until calibration is done and
contact is ≥ 3 on all six sensors used. Tested on the headset on 2026-09-27:
10/10 each, no false triggers, no cross-talk.

## Run

```
uv sync                      # or: python -m pip install websocket-client
python -m sensor.main        # needs EMOTIV_CLIENT_ID / EMOTIV_CLIENT_SECRET in .env
```

Sit still, eyes open, jaw relaxed for the first 20 s. Other options:

```
python -m sensor.main --source synthetic          # no headset: scripted clenches / eyes closed
python -m sensor.main --source replay --replay-file data/sessions/<file>.jsonl
python -m sensor.main --calibration-s 15 --no-record
```

Recording is disabled by default. Setting `sensor.record: true` records raw
packets and triggers to `data/sessions/*.jsonl` (ignored by git). Runtime settings
are in the `sensor:` section of `config.yaml`; CLI options override them. Both P1
and the backend validate these settings with `shared.config.SensorSettings`.

## Messages (5555)

`bci.bandpower` (8 Hz), `bci.trigger_level` (8 Hz, z-scores),
`bci.trigger` (`role` next/select, `kind` jaw_clench/eyes_closed, `strength`,
`contaminated`, required `event_id`), `bci.status` (1 Hz). Models live in
`shared/schemas.py` and are accepted by the shared bus. `sensor/messages.py`
re-exports them for compatibility. Preserve event IDs when forwarding messages;
backend scan integration is still required.

## Files

- `settings.py` — loader and compatibility imports for shared settings
- `engine.py` — calibration, gating, detection (pure logic)
- `triggers/base.py` — hold / release / refractory detector
- `sources/` — `cortex.py` (live), `synthetic.py`, `replay.py`, `cortex_client.py`
- `recorder.py` — background JSONL writer
- `main.py` — process loop and ZMQ
