# ARCHITECTURE

**Flick — a semantic brain–computer interface for assistive communication.**

This document is the single source of truth for the system. Numeric constants are normative; where a constant is tunable it lives in `config.yaml` (§5) and code reads it from there. No magic numbers in source.

---

## 0. How to read this

**Revision 2026-09-27: Emotiv step scanning and Tiger memory.** Target architecture
only: runtime still uses previous contracts and Kuzu. See §27 for actual code
and migration work. Examples below are future contract/config targets, not
permission to edit frozen interfaces in this documentation task. The supplied
review prompt and merge checklist are background; this revision
records the new design and required implementation work without performing it.

- §1–§3 define what is being built and how the processes fit together.
- §4–§6 are the contracts: repository layout, configuration, and every message schema. **These are frozen first and everything else depends on them.**
- §7 is the input abstraction. Read it before writing any code that consumes a user selection.
- §8–§20 specify each subsystem.
- §21–§26 cover build sequencing, failure handling, acceptance criteria and submission.
- §27 distinguishes current implementation from the required migration.

---

## 1. Product definition

### 1.1 What it does

A person who cannot speak uses an **Emotiv EPOC X** and static browser tiles.
STT transcribes their conversational partner; partner identification and personal
memory retrieval ground **three intent labels**. The application appends
**Spell…** and **Cancel**. A trained Emotiv mental command (`push`, trained with
attempted movement of one arm) moves the highlight right, wrapping around. A
**jaw clench selects** the highlighted tile. Nothing advances on a timer; a next
event alone never selects. There is no flicker or gaze-to-frequency mapping.

The chosen intent, or text entered through Spell, drives a second retrieval
round and three grounded candidate sentences. A second selection dispatches
speech through the existing voice chain. Validated grounding is reinforced and
new facts are extracted before the next utterance is accepted. The 3D memory
graph displays retrieval, grounding and learning.

### 1.2 Semantic choices and spelling

Intent selection remains primary. Spell is a first-class escape hatch for names,
places and topics absent from generated choices, not a contrast-only demo.
Personal suggestions reduce spelling work; the binary letter path works without
an LLM. Do not claim fixed sentence latency, words per minute or accuracy until
the new path has been measured.

### 1.3 Rounds

| Round | Ordered tiles | Cancel index (zero-based) | Priority |
|---|---|---|---|
| Intent | 3 intents, Spell…, Cancel | 4 | P0 |
| Candidate | 3 sentence slots, Cancel | 3 | P0 |
| Spell | 0–3 suggestions, up to 2 symbol groups, Cancel | `len(labels) - 1`, up to 5 | P1, required |

There is no global five-tile limit. Candidate fallback preserves the selected
intent verbatim in slot 0, disables empty slots 1–2, and keeps Cancel at index 3.
Scan skips disabled slots. Spell can have **six tiles**, all reachable with
next/select even though direct keyboard shortcuts cover only keys 1–5.

### 1.4 Non-goals

No SSVEP/sequential flicker, FBCCA/eTRCA, raw-EEG filtering, refresh profiles,
LSL, multi-command motor-imagery classification, gaze control or PsychoPy in the
active product. No VR, environmental control, Raspberry Pi, local neural voice
cloning, speaker voice embeddings or multilingual output. OpenBCI is a separately
reviewed contingency, not an automatic runtime fallback. Manual offline-mode
switching remains removed.

### 1.5 Sponsor alignment

Target integrations, not claims that all are implemented:

| Track | Purpose | Priority |
|---|---|---|
| Microsoft — What's Missing? | Static scan tiles and personal memory graph; AI within an assistive communication pipeline | P0 |
| ElevenLabs | Consented voice cloning and speech fallback chain (§15) | P0 |
| Gemini | Intents, candidates, partner identification, extraction and onboarding (§12, §14) | P0 |
| Tiger Data | Persistent profile/memory graph, conversations, learning history and Cortex/scan telemetry (§10, §18) | Core store required |
| DigitalOcean | Outbound spectator relay and configured Gradient LLM fallback (§19) | P2 |
| GoDaddy Registry | Spectator domain | P2 |
| Assurant | Accurate outbound ledger, cost visibility, purge and automatic fallbacks (§20) | P3 |

---

## 2. Decision register

### 2.1 Hardware

| ID | Decision |
|---|---|
| HW-1 | **Emotiv EPOC X, free Cortex tier**, replaces Cyton. Raw EEG is unavailable on the team's entitlement. |
| HW-2 | Use `com`, `fac`, `pow`, `dev`, `eq`. Band power is not raw EEG. |
| HW-3 | One PC, built-in 165 Hz panel, RTX 5050; pilot and dashboard are browser views. No second computer required. |
| HW-4 | Use supported headset setup and contact-quality checks; Cyton montage/gel/dongle requirements are retired. |
| HW-5 | Teammate reports 4.7 fps on Intel versus 165 fps on NVIDIA. Select NVIDIA for browser/Python graphics in Windows settings, then verify locally. This does not introduce CUDA inference. |
| HW-6 | OpenBCI is contingency only. Device failure must not silently become synthetic “live” input. |

### 2.2 Interaction

| ID | Decision |
|---|---|
| UX-1 | Intent → candidates → speech, optionally via Spell. |
| UX-2 | Counts and Cancel position are per round (§1.3), published in `scan.targets`. |
| UX-3 | **No flicker anywhere in the product.** Highlight moves only on accepted next. |
| UX-4 | No accepted select means no Selection, including during noise/startup/timeout. |
| UX-5 | Next = trained mental command; select = jaw clench; independent holds, shared refractory interval. |
| UX-6 | Partner identity still resolves from graph people, with validated persistent manual override. |
| UX-7 | English; configurable frequency-ordered alphabet plus SPACE/DELETE/DONE. |

### 2.3 Cortex bridge and triggers

| ID | Decision |
|---|---|
| DSP-1 | P1 reads Cortex streams, detects next/select and records diagnostics; it knows nothing about tiles. |
| DSP-2 | Next: `com.action == push`, power ≥ 0.45 for 0.5 s. |
| DSP-3 | Select: `fac.lAct == clench`, `lPow` ≥ 0.5 for 0.2 s. |
| DSP-4 | Shared 0.8 s refractory after either event; release required before the same sustained action fires again. |
| DSP-5 | Facial activity above 0.3 overlapping next marks `contaminated`, exposed in UI and telemetry. |
| DSP-6 | No live triggers before connected session, loaded/trained profile and acceptable contact quality. Missing/stale samples reset holds. |

These are tunable starting values, **not validated headset thresholds**. All
thresholds, holds and freshness tolerances live in §5 configuration.

### 2.4 Software

| ID | Decision |
|---|---|
| SW-1 | Python 3.11, `uv`. |
| SW-2 | FastAPI/uvicorn; Vite/React/TypeScript/Tailwind; `/pilot` in the existing frontend. |
| SW-3 | **Tiger Data: PostgreSQL + TimescaleDB + pgvector**, replacing Kuzu after migration; persistent mirror/outbox for interruptions (§10). |
| SW-4 | Local CPU MiniLM, 384 dimensions, existing deterministic embedding fallback; retain embedding provenance/compatibility. |
| SW-5 | Facility-location greedy selection **in NumPy**, matching current code; no apricot runtime requirement. |
| SW-6 | Gemini → configured OpenAI-compatible → configured Gradient → explicit static fallback. |
| SW-7 | Deepgram → local faster-whisper small → manual text. |
| SW-8 | Audio cache → ElevenLabs → installed Piper → browser speech. |
| SW-9 | Python inference remains CPU-only. NVIDIA display configuration does not authorize CUDA dependencies. |
| SW-10 | Preserve reinforcement, extraction threshold/cap/dedup and next-turn retrieval; distinguish pending from remotely committed writes. |
| SW-11 | Atomic biography onboarding; demo fixture only for unchanged demo identity/biography (§14). |
| SW-12 | P1 sensor and P3 backend plus P4 frontend; no P2. ZMQ P1↔P3, WebSocket P3↔browser. |
| SW-13 | Explicit automatic fallbacks; missing memory or failed persistence is never fabricated success. |
| SW-14 | Telemetry is best-effort/droppable. Memory mutations must be durable or reported unsuccessful; separate pools/queues. |
| SW-15 | Spectator stays outbound-only, cannot inject input/training commands. |
| SW-16 | No manual offline switch; status names actual input source, trigger modality and memory store. |

### 2.5 Demo integrity

| ID | Decision |
|---|---|
| DEMO-1 | No hidden manual triggering of headset selections. |
| DEMO-2 | Replay recorded Cortex streams through the same detectors/scan logic; persistent `REPLAY` badge. Synthetic streams show `SYNTHETIC SIGNAL`. |
| DEMO-3 | Always show **NEXT: MENTAL COMMAND** and **SELECT: JAW CLENCH (MUSCLE)**, plus `KEYBOARD INPUT` where applicable. |
| DEMO-4 | Manual partner text bypasses only the microphone, never next/select. Keyboard demos are disclosed. |
| DEMO-5 | Record streams, detector configuration, profile/training provenance, triggers and scan transitions; exclude credentials. |
| DEMO-6 | Say “A trained Emotiv mental command for attempted arm movement moves the highlight; a jaw clench detected by the headset selects.” Never claim thought reading or isolated neural origin. |

### 2.6 Evidence and validation status

Source: Zahid's supplied `REVIEW_NOTES.md`, `CHANGELOG.md` and
`ARCHITECTURE_ADDITIONS.md`, dated 2026-09-27. These are teammate-reported
observations/design inputs; this revision did not rerun experiments or verify
Cortex entitlement/API details independently.

Sequential flicker: reported 13/30 tile identifications (43%, chance 33%, p=0.17),
4/10 false selections in the look-away control, no measurable O1/O2 low-beta
signal-check effect, and facial activity 25–42% during runs versus 2–5% at rest.
A separate 13-minute observation reported one spontaneous clench, 207 smile/smirk
and 68 laugh detections. This motivates removing flicker and excluding smiles,
laughs, blinks, winks, look-direction and multiple mental commands. It does **not**
establish next/select accuracy. The 20-trial headset validation remains pending.
Experiment code is reported on the teammate's branch, not present in inspected
`main`; preserve it as evidence when merged, not product stimulus.

---

## 3. Topology

### 3.1 One machine

```text
EPOC X → Emotiv Launcher / Cortex (local secure WebSocket)
                 ↓
P1: bridge, training, detectors, recording
    PUB 5555 → P3 backend → WebSocket → /pilot + dashboard
    SUB 5556 ← P3 training/profile control
                 ↓
       Tiger memory + telemetry
       persistent local mirror/outbox
P4 serves both browser views; P2 is removed.
```

Authorize Cortex before fullscreen: Launcher approval may block for a minute.
Pilot view and operator dashboard are on the same PC; simultaneous display can
use a window arrangement or optional extra display, not a required second PC.

### 3.2 Processes

| Process | Entry point | Binds | Connects to |
|---|---|---|---|
| P1 | `python -m sensor.main` | ZMQ PUB `tcp://127.0.0.1:5555` | Cortex; SUB `5556` |
| P3 | `uvicorn backend.app.main:app --host 0.0.0.0 --port 8000` | HTTP/WS `8000`, PUB `5556` | SUB `5555`; database pools |
| P4 | `npm run dev` | HTTP `5173`, proxies `/api`, `/ws` | Browser clients use P3 |

P3 owns one control publisher; adapters do not compete to bind 5556. Retire
5557, `stim.*` and LSL. Models, embeddings, providers and storage never block P1.

### 3.3 One turn

```text
partner → STT → partner ID → retrieval 1 → three intents
 → scan.targets [intents, Spell…, Cancel] → next/select
 → chosen intent OR Spell → DONE with user text
 → retrieval 2 → three grounded candidates → scan.targets → select
 → speech + correlated playback acknowledgment
 → reinforce/extract → durable commit or explicitly pending outbox
 → bloom/snapshot/history → IDLE → next-turn retrieval
```

---

## 4. Repository layout

**Target layout**, not an implementation inventory; see §27 for existing code.

| Area | Retain/update | Add | Retire from active product |
|---|---|---|---|
| Shared | `shared/{schemas,config,bus,logging}.py`, `config.yaml` | New models/contracts in these modules | Raw EEG, scores, `stim.*` contracts |
| Inputs | `inputs/{base,keyboard,replay}.py` | `inputs/{bci,scan}.py` | `inputs/ssvep.py`; optional `inputs/emotiv.py` proposal |
| Sensor | Recording and synthetic/replay concepts | `sensor/main.py`, `sources/{cortex,synthetic,replay}.py`, `triggers/{mental_command,jaw_clench}.py`, `training.py`, `recorder.py` | Cyton production path, DSP/classifiers/calibration |
| Backend | FSM, services/providers/prompts | `backend/app/services/db.py`, `backend/data/lexicon_en.txt` | Stimulus publisher and mode toggle |
| Frontend | Dashboard, onboarding, graph, conversation, playback, privacy, spectator | `views/Pilot.tsx`, ScanPanel, SpellPanel, MuscleStrip, BandPowerPlot, HeadsetQuality, MemoryTimeline | EegTrace, PsdPlot, TargetScores |
| Storage | Existing-data migration tooling | `migrations/001_memory.sql`, `002_timeseries.sql` target baselines | Kuzu runtime after verified migration; old telemetry schema after upgrade |
| Tools | `run.sh`, session/replay tooling, tests | Headset training/cued-block tools, trigger fixtures | `stimulus/`, `scripts/check_stimulus.py` |
| Evidence | Preserve teammate experiment history | `experiments/seq_flicker/` | Never run experiments as product stimulus |

Do not overwrite an applied migration. Existing `001_timescale.sql` needs an
upgrade plan before new baseline names are used on an existing DB. Preserve
`data/` and existing Kuzu data until a verified reversible migration completes.

---

## 5. Configuration

**Target delta, not applied to runtime files by this revision.** Retain unmentioned
provider, retrieval, reinforcement, extraction, voice, privacy, spectator and
recording settings. Frozen edits still require AGENTS.md §4 confirmation and a
coordinated contract commit.

Remove `mode.targets`, `eeg`, `dsp`, `stimulus`, `classify`, `decision`, old
calibration fields, `graph.db_path`. Rename telemetry `eeg_downsample` to
`signal_downsample`. Do not restore `privacy.local_mode` / `LOCAL_MODE`.

```yaml
input:
  adapter: keyboard          # keyboard | bci | replay
  replay_file: null
mode:
  source: synthetic          # emotiv | synthetic | replay
  next_trigger: mental_command
  select_trigger: jaw_clench
emotiv:
  cortex_url: wss://localhost:6868
  profile: flick-pilot
  headset_id: auto
  streams: [com, fac, pow, dev, eq]
  min_contact_quality: 3
scan:
  trial_timeout_s: 60
  hold_after_select_s: 0.6
  start_idx: 0
triggers:
  refractory_s: 0.8
  contamination_threshold: 0.3
  max_sample_gap_s: 0.5       # added: reset holds across stale data
  mental_command: {stream: com, action: push, min_power: 0.45, hold_s: 0.5}
  jaw_clench: {stream: fac, field: lAct, action: clench, min_power: 0.5, hold_s: 0.2}
speller:
  n: 2                      # explicit; current service defaults to 4
  alphabet: "ETAOINSHRDLCUMWFGYPBVKJXQZ"
  specials: [SPACE, DELETE, DONE]
  n_suggestions: 3
  suggestion_sources: [memory, lexicon, llm]
  lexicon_path: ./backend/data/lexicon_en.txt
  min_prefix_for_llm: 2
calibration:
  neutral_trials: 3
  command_trials: 5
  training_trial_s: 8.0
  cued_block_trials: 20
database:
  memory_pool_max: 5
  telemetry_pool_max: 3
  query_timeout_s: 0.3
  write_timeout_s: 1.0
  outbox_retry_s: 5.0
  mirror_dir: ./data/memory_mirror   # added: durable snapshot/journal
graph:
  profile_id: user
  embedding_dim: 384
generation:
  n_intents: 3
  n_candidates: 3
  max_tokens: 2048
  timeout_s: 12.0
  transient_retries: 1
  retry_delay_s: 0.5
  retry_jitter_s: 0.25
  min_attempt_budget_s: 2.0
telemetry:
  enabled: true
  queue_maxsize: 2000
  flush_interval_ms: 500
  flush_batch: 500
  signal_downsample: 1
  compress_after: 10m
```

Freshness, training duration, `speller.n` and durable mirror path close omissions
in the supplied sketch. Validate bounds, durations, alphabet uniqueness and
stream availability. These defaults require headset testing, not hardcoding.

Environment: `TIMESCALE_DSN` → **`TIGER_DSN`**; add **`LOCAL_PG_DSN`** for an
explicit local TimescaleDB+pgvector development/test database (for example
`timescale/timescaledb-ha`, extensions verified). Keep `EMOTIV_CLIENT_ID` and
`EMOTIV_CLIENT_SECRET`; other provider settings unchanged. Migrate legacy DSNs
explicitly during rollout; never print credentials. Local DB configuration is
not a global offline switch or automatic failover into a second independent DB.

Preserve automatic chains in SW-6–SW-8 and MiniLM → deterministic embeddings.
Each LLM stage shares one 12 s deadline across provider attempts, one transient
retry and one JSON repair. Retry delay 0.5 s + 0–0.25 s jitter (or longer provider
guidance), only if ≥2 s remain afterward. Immediate 429 cooldown and failed/skipped
transient retry cooldown remain ≥30 s. Onboarding keeps 4000 tokens per pass.
Browser speech can use network voices; no all-on-device guarantee is made.

---

## 6. Contracts

**Next contract revision**, not currently shipped schemas. Preserve `type`, UNIX
seconds `ts`, validation and Python/TypeScript parity. Approve/finalize the
coordinated change before migrating processes (§27).

### 6.1 Selection

```python
class Selection(BaseModel):
    type: Literal["input.selection"]
    ts: float
    trial_id: str
    target_idx: int                  # this trial's labels
    confidence: float               # strength, not measured accuracy
    source: str                     # bci | keyboard | replay
    algorithm: str | None           # step_scan | None
    trigger: str | None = None      # jaw_clench for BCI select
    moves: int = 0                  # accepted next events this trial
```

At most one Selection per trial. Select strength supplies BCI confidence;
manual input retains confidence 1.0 with its badge. Status/telemetry separately
identify actual signal source so synthetic BCI never looks live.

### 6.2 P1 → P3, ZMQ 5555

Replace EegChunk, PsdFrame, TargetScores, SensorSelection and old SensorStatus:

```python
class BandPowerFrame(BaseModel):
    type: Literal["bci.bandpower"]
    ts: float
    sensors: list[str]
    bands: list[str]
    power: list[list[float]]         # [sensor][band], reported uV²/Hz

class TriggerLevel(BaseModel):
    type: Literal["bci.trigger_level"]
    ts: float
    next_level: float
    next_threshold: float
    select_level: float
    select_threshold: float
    facial_action: str | None
    facial_power: float

class TriggerEvent(BaseModel):
    type: Literal["bci.trigger"]
    ts: float
    role: Literal["next", "select"]
    kind: str
    strength: float
    contaminated: bool

class SensorStatus(BaseModel):
    type: Literal["bci.status"]
    ts: float
    source: Literal["emotiv", "synthetic", "replay"]
    connected: bool
    headset_id: str | None
    battery_pct: int | None
    contact_quality: dict[str, int]
    eeg_quality: float | None
    streams: list[str]
    next_trigger: str
    select_trigger: str
    profile_loaded: bool
    trained_actions: list[str]
    dropped_samples: int
```

Band power 8 Hz; levels around 8 Hz; status 1 Hz; triggers on accepted events.
Validate dimensions; normalize timestamps to the local event clock while keeping
source timestamps for replay. P1 never adds tile indices/trial IDs. P3 rejects
events older than trial activation, duplicates, stale data and closed trials.
Document Cortex-to-normalized field mapping and contact-quality scale in the
bridge; do not assume raw array positions or a scale from the illustrative names.

### 6.3 P3 → P1 control, ZMQ 5556

Retire `stim.*`, stimulus profile/onset/integrity and port 5557.

```python
class SensorControl(BaseModel):
    type: Literal["sensor.control"]
    ts: float
    action: Literal["train", "train_accept", "train_reject", "reload_profile"]
    train_action: str | None         # neutral | push where applicable
```

Training receipt is not completion. REST training status must report confirmed
Cortex progress/errors, not assume a PUB send succeeded. Training/profile changes
require no active trial. No spectator-originated controls.

### 6.4 Browser → P3

Retain `client.request_snapshot`, `client.key_press`, `client.playback_complete`
and existing playback ID/outcome semantics. Extend keys to `n`, `s`, `1`–`5`.
Add required `trial_id` to scanning key messages in the coordinated revision:
a queued key from an old screen cannot act on a newly displayed trial. The sixth
Spell tile is reachable with `n`/`s`. Ignore disabled/out-of-range picks; only the
keyboard adapter handles these messages.

### 6.5 P3 → browser

Envelope: `{"type": ..., "ts": ..., "payload": {...}}`.

| Type | Payload / behavior |
|---|---|
| `scan.targets` | `{trial_id, labels, round, cancel_idx, highlight_idx, cue_idx}`; authoritative screen, round = intent/candidate/speller |
| `scan.highlight` | `{trial_id, highlight_idx}` |
| `scan.selected` | `{trial_id, target_idx, hold_s}`; visual hold, not another selection |
| `scan.idle` | `{reason}`; clears interaction |
| `spell.state` | `{trial_id, text, current_word, groups, suggestions}`; trial ID added against stale state/suggestions |
| `eeg.bandpower` | BandPowerFrame data, replacing trace/PSD; never labeled raw EEG |
| `bci.trigger_level`, `bci.trigger` | Respective sensor data, including contamination |
| `input.selection` | Existing label/index/round/confidence/source plus trial ID, algorithm, trigger, moves |
| `conv.transcript` | Existing text/speaker/partner/confidence |
| `conv.intents` | Existing labels/source/fallback_reason plus trial ID and cancel_idx; full five-tile list |
| `conv.candidates` | Existing candidates/grounding/source/fallback_reason plus trial ID and cancel_idx; full four-slot list |
| `conv.spoken` | Preserve text/voice/cache/latency/audio and correlated playback ID/deadline |
| `graph.snapshot`, `graph.activate`, `graph.bloom` | Preserve stable node/edge IDs, weights, traversal reason and grounding |
| `fsm.state` | `{state, detail}`; adds SPELLING, retires old SPELLER_WAIT path |
| `sys.status` | Retain input/source/connected/replay/providers/drop counts; add next_trigger, select_trigger, battery_pct, contact_quality, profile_loaded, memory_store |
| `analytics.summary` | Scan metrics (§18); retain unrelated fields only where meaningful |
| `privacy.flow`, `privacy.cost`, `spectator.link` | Existing purposes/envelopes |

Remove old status `profile` (stimulus), refresh/integrity, frequencies and
`decision`. Cancel belongs to trial messages, not global status. `memory_store`
is `tiger | mirror | fixture`; allow null/unavailable before a usable store exists.
Add pending-memory-operation count. Local Postgres uses the same engine mode;
the privacy ledger must still distinguish the actual destination.
`fixture` identifies an explicitly disclosed, unchanged-demo fixture session;
record its actual persistence destination separately rather than conflating
fixture provenance with remote durability.

GraphNode/GraphEdge fields remain compatible. Reconcile snapshots by ID/weight;
repeated blooms never duplicate data. Reconnect restores snapshot/status, active
scan targets/highlight, matching conversation/Spell state, then FSM state without
a new trial, reset highlight or replayed speech. Ignore mismatched-trial deltas.

**Playback remains gated.** Preserve acknowledgment only after audio ends/stops,
with matching reply ID and recipient. Missing/disconnected recipients keep capture
muted until restart as implemented. `/pilot` must not duplicate audio or require
acknowledgments from passive views: designate an audio-owning view in the later
browser contract. Current Hub sends speech to every connection, so dual-view
integration is required (§27). Retain the existing 30 s playback safety deadline
independently of the new 60 s scan wait; manual prompts remain available.

### 6.6 REST

| Method / path | Target behavior |
|---|---|
| Existing health, graph, onboarding, partner, utterance routes | Preserve successful shapes and seed validation/409/503 behavior |
| `POST /api/input {adapter}` | keyboard/bci/replay; idle/unseeded, listener restart and rollback |
| `POST /api/cued_block/start {n_trials}` | Actual cued scan trials; remove train_etrca |
| `POST /api/training/start {action, trials}` | Neutral/push training; accepted/job status, not premature success |
| `GET /api/training/status` | Confirmed profile/training progress/errors |
| `GET /api/memory/timeline?since=` | Active-profile learning events with pending/committed status |
| `GET /api/speller/suggest?prefix=` | Memory/lexicon/optional LLM ranking; reject obsolete-prefix results |
| Existing session/latest, analytics, privacy and spectator routes | Adapt storage/session formats while preserving boundaries |
| Retired `POST /api/mode` | Normal 404; Spell entered through its tile |

Retire `/api/calibration/start` from the spec (absent in inspected backend).
`/api/privacy/local_mode` remains retired/404.

---

## 7. Input and scan layer

### 7.1 Responsibilities

Keep InputSource `start`, `stop`, `set_targets(trial_id, labels, round)`,
`selections`, `status`. `n_targets` becomes current label count, not a fixed
constructor limit. Adapters share `inputs/scan.py`; renderers never compute their
own highlights. Validate final Cancel label and publish its index.

### 7.2 Trial lifecycle

1. set_targets closes prior state, resets moves, starts at configured index 0 or
   first enabled slot, publishes scan.targets with a fresh trial ID.
2. next advances once to the next enabled tile, wraps, publishes scan.highlight.
3. select snapshots that index, closes the trial, emits one Selection and
   scan.selected, then holds the visual result for configured 0.6 s.
4. No select within scan.trial_timeout_s emits scan.idle and returns FSM to IDLE.

No triggers in the visual hold, generation, speech, learning or closed trials.
Do not carry held clench into the next screen. If next/select arrive together,
select uses the pre-event highlight and competing next is discarded, avoiding
move-and-select of an unintended tile. Freshness checks survive adapter changes.

### 7.3 Adapters

| Adapter | Behavior | Disclosure |
|---|---|---|
| bci | TriggerEvents → backend highlight/Selection | Mental-command/muscle labels plus real acquisition source |
| keyboard | n next, s select, 1–5 direct pick | KEYBOARD INPUT |
| replay | Recorded Cortex inputs → real detectors → shared scan | REPLAY + session provenance |

Synthetic data exercises the same detectors and shows SYNTHETIC SIGNAL. Device
failure cannot silently switch source. Retire SSVEP and band-power/wink modes.

### 7.4 Hot-swap

Preserve existing idle/unseeded restriction, listener restart, cleanup and
rollback on failed startup. Remove stimulus ownership; clear queued triggers and
selections. Status updates immediately; unsupported adapters return HTTP 422.

---

## 8. Sensor process (P1)

### 8.1 Acquisition

Reported Cortex flow: requestAccess → authorize → queryHeadsets/controlDevice
connect → createSession → setupProfile load → subscribe. Verify actual SDK/API
schemas, permissions and stream availability before implementation; these are
teammate-reported rates, not measurements made by this revision.

| Stream | Reported rate | Use |
|---|---|---|
| com | 8 Hz | Trained command action/power |
| fac | 32 Hz | Lower-face clench/power; contamination |
| pow | 8 Hz | Sensor bands; each sample summarizes prior 2 s, uV²/Hz |
| dev | Device updates | Contact quality/battery |
| eq | Quality updates | Signal quality |
| met | 0.1 Hz free tier | Not used |

Band power is diagnostic, not SSVEP input. No raw EEG/DSP/FBCCA/eTRCA/LSL stages.
Recording uses a bounded writer off the acquisition loop, reporting losses;
no database, model loading or blocking disk/network work in that loop beyond
the Cortex acquisition itself.

### 8.2 Detectors

Accumulate hold only over fresh matching samples above threshold; reset on action
change, low power, bad contact or gaps. Fire once after hold_s, suppress both
roles through shared refractory, require release before rearming sustained input.
Use elapsed source/monotonic time, not sample counts. Facial activity overlapping
the next hold marks contamination. Missing quality/facial streams are not proof
of clean input; withhold live triggers until required streams are fresh.

### 8.3 Training

Cortex training: neutral ×3, push ×5, 8 s each, explicit accept/reject, saved to
flick-pilot. Reported ~10 min includes setup/retries beyond 64 s acquisition.
Training disables scan; confirmed loaded profile/trained actions precede arming.
Failure or rejected training cannot mark readiness.

### 8.4 Synthetic, recording, replay

Synthetic scenarios cover noise, intentional holds, brief bursts, sustained and
simultaneous actions, contamination and disconnects through real detectors.
Record Cortex packets, original/normalized timestamps, configuration, profile/
training metadata, source, triggers and scan targets/highlights/selections.
A versioned manifest supports original-pace replay with trial context; stored
selections are reference results, not injected live outcomes. Old raw-EEG .npz
sessions are not automatically compatible; update latest-session/replay tooling.

---

## 9. Pilot view (replaces P2)

`frontend/src/views/Pilot.tsx` at **/pilot**, fullscreen on built-in panel:

- High-contrast static row of up to six tiles; backend highlight gets a thick
  bright border and lighter fill. No flicker or frame-exact classification.
- Next/select meters and threshold lines with persistent modality labels.
- Spell text above row, current word underlined, matching trial/state IDs.
- scan.selected makes selected tile solid for hold_s; short tone only in the
  designated feedback/audio view, not every connected browser.
- Timeout/disconnect disables input; reconnect restores backend state without
  moving the highlight. Preserve source badges and contamination disclosure.
- Integrate the existing speech playback handshake as specified in §6.5.

---

## 10. Memory store and graph service

### 10.1 Tiger Data schema

Target: one PostgreSQL deployment with TimescaleDB and pgvector for profile,
graph, conversations, learning history and telemetry. **Current runtime is still
Kuzu.** Migrate data explicitly; a schema document is not a completed port.

The following logical baseline adjusts the supplied sketch to scope IDs and
foreign keys to a profile. It preserves `user` as the self Person ID within the
active profile; it does not authorize a persona-switching feature.

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE profiles (
  id TEXT PRIMARY KEY, display_name TEXT NOT NULL, bio TEXT, shared_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE nodes (
  profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('Person','Place','Thing','Activity','Need','Memory')),
  name TEXT, text TEXT, attrs JSONB NOT NULL DEFAULT '{}',
  embedding vector(384) NOT NULL,
  weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_accessed TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (profile_id, id),
  CHECK ((kind = 'Memory' AND text IS NOT NULL) OR
         (kind <> 'Memory' AND name IS NOT NULL)));
CREATE INDEX nodes_embedding ON nodes USING hnsw (embedding vector_cosine_ops);

CREATE TABLE edge_rules (
  kind TEXT, src_kind TEXT, dst_kind TEXT,
  PRIMARY KEY (kind, src_kind, dst_kind));

CREATE TABLE edges (
  profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  id TEXT NOT NULL, kind TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL,
  weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  count BIGINT NOT NULL DEFAULT 1,
  strength DOUBLE PRECISION,
  last_reinforced TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (profile_id, id),
  FOREIGN KEY (profile_id, src) REFERENCES nodes(profile_id, id) ON DELETE CASCADE,
  FOREIGN KEY (profile_id, dst) REFERENCES nodes(profile_id, id) ON DELETE CASCADE,
  UNIQUE (profile_id, kind, src, dst));
```

`attrs` retains relationship, address_terms, category, notes, urgency,
time_of_day, occurred_on and source as appropriate. Preserve all current node
facts and stable IDs; Memory content belongs in `text`. Validate nonblank content,
finite embedding dimensions/weights, and source/destination kinds. Populate
edge_rules from current REL_PAIRS and enforce them transactionally; merely
creating an edge_rules table does not constrain inserts.

| Relation | Allowed pairs |
|---|---|
| KNOWS | Person → Person |
| LIKES | Person → Thing / Activity / Place / Person |
| DISLIKES | Person → Thing / Activity / Place |
| NEEDS | Person → Need / Thing |
| LOCATED_AT | Thing / Activity / Person → Place |
| DOES | Person → Activity |
| INVOLVES | Memory → Person / Place / Thing / Activity |
| RELATES_TO | Thing → Thing / Activity; Activity → Activity; Need → Thing |

Keep LIKES/DISLIKES separate and strength in [0,1]. Self Person remains
`id=user`, `relationship=self`; profile display_name and that Person must agree.
Profile/identity absence means UNSEEDED, not automatic demo substitution.

### 10.2 Service compatibility and queries

Preserve GraphService method names, domain result models and semantics:
ensure_schema, seed_from_json, snapshot, vector_search, expand, reinforce,
upsert_node, upsert_edge, people, node_count, **get_node, edges_among,
get_embeddings, transaction and close**. The last five exist and have callers,
although the teammate's abbreviated interface omits them. Retain NodeRef,
EdgeRef, Person and SeedResult contracts, relation checks, stable edge IDs,
cache invalidation and deterministic ordering/tie-breaking.

Database vector search is profile-filtered cosine distance:
`WHERE profile_id = $1 ORDER BY embedding <=> $2 LIMIT $3`. Expansion is a
bounded, cycle-safe, undirected recursive CTE (normally two hops), unioning seeds
and preferring higher-weight nodes up to candidate_cap. Preserve edges_among and
partner conditioning; an index must not silently lose same-profile candidates.
The mirror uses the same cosine and graph semantics with cached NumPy arrays.
Zero vectors and unavailable embeddings require defined behavior, not invented
similarity; do not mix incompatible MiniLM/hash spaces without rebuilding.

Keeping method names is **not sufficient for a drop-in asyncpg port**. Existing
graph calls are synchronous and run on MemoryWorker; proposed `db.py` owns async
database pools/timeouts. Reconcile this boundary deliberately: embeddings/local
mirror work stays off the event loop; remote requests stay async; ordered writes
must finish their durability step before callers report success. Never invoke
blocking SQL or nest an event loop inside a running request. Update internal
protocols and callers where needed, retaining their returned domain contracts.

### 10.3 Mirror, outbox and consistency

- Separate memory and telemetry pools (5/3 maximum connections initially).
  Remote query deadline 0.3 s, write deadline 1 s, outbox retry every 5 s.
- Hydrate a profile-scoped in-process mirror with a durable local snapshot/journal
  under database.mirror_dir. Use it for bounded conversational reads and when
  remote queries fail/expire. A 0.3 s remote timeout exceeds the 150 ms retrieval
  target: keep warm-mirror retrieval on the critical path, refresh remotely off
  that path, and report cold-load/recovery latency separately.
- Normal writes atomically commit graph changes plus their learning-history
  events in PostgreSQL, then update the mirror and invalidate retrieval caches.
- A remote timeout may mean the server committed but the response was lost.
  Every logical mutation therefore needs a stable operation ID and deduplication
  ledger in the same remote transaction; retries cannot double-increment weights,
  create duplicate edges, or duplicate learning events.
- On failed remote write, durably journal the complete ordered mutation and its
  ID **before** applying it to the mirror. Mark it pending and expose count/store
  state; it can participate in next-turn retrieval, but is not “saved to Tiger”.
  In-memory-only queues cannot satisfy restart persistence. If neither remote
  commit nor local journal succeeds, report failure and do not publish a learned
  bloom or alter accepted memory state.
- Reconnect replays operations in order, preserves pending mutations while
  refreshing the snapshot, and acknowledges each operation only after confirmed
  remote durability. Restart loads the snapshot plus journal before accepting
  a turn. Tests must cover ambiguous commit, replay twice, and crash recovery.
- Cold start without Tiger and without a valid mirror cannot invent a seeded
  identity; report storage unavailable. The demo fixture is a disclosed source
  only under §14's unchanged-demo rule, never a replacement for a custom profile.
- Initial onboarding requires one remote PostgreSQL transaction (profile, user,
  accepted nodes/edges and seed event). Failure leaves onboarding incomplete;
  do not defer a partial seed to the outbox and call it complete.

Purge invalidates/cancels older queued writes with an ordered tombstone or profile
generation so outbox replay cannot resurrect deleted memory. A purge queued during
an outage is pending, not confirmed remote deletion. Telemetry's drop queue must
never hold memory mutations or their authoritative learning history.

### 10.4 Migration gate

Before removing Kuzu: export existing graph data without modifying the original,
import into one PostgreSQL transaction, compare identity, IDs, facts, relations,
weights, counts and retrieval, then run two-turn and restart tests against real
local TimescaleDB/pgvector. Keep a rollback copy and explicit migration version.
Do not silently reseed, overwrite custom biographies or drop existing data.

---

## 11. Retrieval

Four stages, target under 150 ms total on a warm local mirror at 150–300 nodes.
Remote synchronization/cold-start latency is measured separately (§10.3).

1. **Seed.** Embed the query (partner utterance for round one; utterance + chosen intent for round two). Cosine against all node embeddings. Top `vector_top_k` (25).
2. **Expand.** Two-hop traversal from seeds, union with seeds, truncate to `candidate_cap` (60) preferring higher weight.
3. **Partner boost.** If a partner is identified, unconditionally add that `Person` node and everything within one hop. **This is what makes the same intent produce a different sentence depending on who is listening**, and it is the most persuasive behaviour in the demo.
4. **Submodular selection.** Greedy facility-location maximization in NumPy over cosine similarities remapped to [0,1], matching `_facility_location_greedy` in the current implementation. The existing profiling notes report apricot at 800–900 ms; retain the measured NumPy approach.

Plain top-K returns eight near-duplicates. Facility location maximises coverage, so you get the dog's name *and* its dietary needs *and* the walking routine, rather than five memories of the same walk. This is a real quality difference in generated sentences, not a line for the pitch.

```python
class RetrievalResult(BaseModel):
    nodes: list[NodeRef]              # the 8 selected
    edges: list[EdgeRef]
    context_text: str
    activated_node_ids: list[str]     # everything traversed
```

`activated_node_ids` is deliberately larger than `nodes`: the dashboard pulses everything traversed, then brightens the eight selected. Judges watch the search happen, then watch it narrow.

Context is rendered one fact per line:

```
- Sofia is your daughter. You call her "mija".
- Sofia visits on Sunday afternoons.
- You dislike the recliner; it hurts your back.
- Rosie is your dog, a nine-year-old beagle.
```

---

## 12. Generation

All calls go through `LLMProvider.complete(system, user, json_mode=...)` with the configured generation token allowance and timeout. Each generation stage has one 12 s deadline shared by all provider attempts, one transient retry and at most one JSON repair. Repair targets the provider that produced malformed model output; a static result never triggers repair. The 2048-token allowance leaves room for thinking and the complete JSON response; Gemini 3 uses low thinking and Gemini 2.5 Flash disables thinking. Failure or the stage deadline yields visibly marked static intents, or one reply containing the selected intent verbatim with empty grounding. Unused candidate slots are disabled; Cancel remains on the last target of the current round. `conv.intents` and `conv.candidates` carry optional `source` (`generated` or `fallback`) and `fallback_reason` metadata, restored on reconnect.

### 12.1 Intent labels

```
You write short intent labels for a speech device used by someone who cannot speak.

They will choose ONE label by next/select step scanning. The label is not the sentence they
will say — it is the DIRECTION their reply will take.

Rules:
- Exactly 3 labels.
- Each label is 1 to 3 words. Never more.
- Labels must be clearly distinct in meaning from one another.
- Cover a genuine range: at minimum one affirmative, one negative or deflecting,
  and one that asks something back.
- Use the person's own world where it helps (names, places, routines from CONTEXT).
- Never include punctuation. Never number them.

Return strict JSON, nothing else:
{"labels": ["...", "...", "..."]}

CONTEXT ABOUT THE PERSON:
{context}

WHO IS SPEAKING TO THEM: {partner_name} ({partner_relationship})
WHAT THEY JUST SAID: "{utterance}"
```

Rendered on tiles 0–2. Tile 3 is Spell… and tile 4 Cancel, both application-owned,
never LLM-generated. Parsing and static fallback must also produce three intents.

### 12.2 Candidate sentences

```
You speak on behalf of {user_name}, who cannot speak. You are writing what they
will say out loud, in their own voice. Write as THEM, in first person.

Produce exactly 3 candidate sentences expressing the chosen intent.

Rules:
- Vary the length: one short (under 8 words), one medium, one longer.
- Ground every specific detail in FACTS below. Do not invent names, places,
  times or relationships that are not there.
- Use their term of address for this listener if FACTS provides one.
- Natural spoken English. Contractions. No emoji, no markdown, no quotes.
- Never apologise for being slow or for using a device.
- Preserve their dignity. They are an adult with opinions, not a patient.

Return strict JSON, nothing else:
{"candidates": ["...", "...", "..."], "grounding": ["node_id", ...]}

"grounding" lists the ids of the FACTS you actually used.

FACTS:
{context}

LISTENER: {partner_name} ({partner_relationship})
THEY SAID: "{utterance}"
CHOSEN INTENT: "{intent}"
```

`grounding` drives the node-highlight animation. Ids not present in the supplied facts are dropped silently rather than failing the turn.

Candidate round has four slots: three candidates then Cancel at index 3, with
`cancel_idx` in trial messages. Fallback has the selected intent verbatim in slot
0, empty disabled slots 1–2, no grounding and explicit fallback metadata. This
supersedes the old global key-5 Cancel mapping. Unknown grounding IDs remain
removed; supplied facts keep stable IDs in prompts.

For a spelled intent append to the candidate prompt:
`The user spelled this themselves; keep their words.` Preserve the actual text,
including names; suggestions or candidate generation cannot silently replace it.
Existing provider deadline, repair limits and fallback provenance still apply.

### 12.3 Partner identification

Receives the transcript and known `Person` nodes with relationships. Returns `{"partner_id", "confidence", "reason"}`. Below 0.6, keep the previous partner. A manual override always wins and persists until changed.

### 12.4 Fact extraction

Runs after each spoken turn with the utterance, the spoken sentence and a graph summary:

```json
{
  "nodes": [{"kind": "Thing", "name": "adjustable chair",
             "notes": "...", "confidence": 0.82}],
  "edges": [{"kind": "NEEDS", "source": "user",
             "target_name": "adjustable chair", "confidence": 0.79}]
}
```

Below `confidence_threshold` discarded; at most `max_new_nodes_per_turn` commit. Each proposal is checked against existing nodes by cosine similarity — above `dedup_similarity` (0.88) it reinforces the existing node instead of creating a duplicate. **Without this check the graph fills with near-identical nodes within five turns.**

New nodes broadcast as `graph.bloom` and animate into place.

---

## 13. Orchestrator and Spell

One application instance and one active conversation task. Each transition
broadcasts fsm.state. Preserve turn locking, partner lookup, both retrieval
rounds, validated grounding, reinforcement/extraction and playback gating.

```text
UNSEEDED --atomic seed--> IDLE
IDLE → TRANSCRIBING → GROUNDING → INTENT_GEN → INTENT_WAIT
INTENT_WAIT --intent--> CANDIDATE_GEN → CANDIDATE_WAIT
INTENT_WAIT --Spell…--> SPELLING --DONE/nonempty text--> CANDIDATE_GEN
INTENT_WAIT --Cancel--> IDLE
SPELLING --Cancel--> INTENT_WAIT (same intent labels)
CANDIDATE_WAIT --Cancel--> INTENT_WAIT (same intent labels)
CANDIDATE_WAIT --sentence--> SPEAKING → LEARNING → IDLE
```

Every active selection wait, including each SPELLING step, uses
scan.trial_timeout_s (60 s initially); expiry emits scan.idle and returns IDLE
with “No selection — listening again”. Generation stages retain their 12 s
budget. Playback keeps its independent safety deadline (§6.5).

Only accept a Selection for the current open trial in INTENT_WAIT,
CANDIDATE_WAIT or SPELLING. Every new screen, including returning to the same
intent labels, gets a fresh trial ID; reconnect does not. Cancel is determined
from the current trial's explicit index. Remove mode-toggle/SPEAK-to-audio flow.

### 13.1 Binary spelling

Retain the existing N-ary tree concept, set `speller.n=2`. Start with frequency
order ETAOINSHRDLCUMWFGYPBVKJXQZ and SPACE, DELETE, DONE. Each screen offers
ranked suggestions, up to two contiguous symbol groups, then Cancel. Selection
of a group descends until a single symbol is chosen; then return to the root.
Labels must make actual group membership understandable: alphabetic “A–Z” range
notation is misleading for a frequency-ordered group. A balanced binary tree
needs roughly five decisions per symbol; ordering alone does not guarantee
shorter paths for common letters, and scan movements add interaction cost.

SPACE appends a space; DELETE removes the last character safely, including on an
empty buffer. A suggestion replaces the current prefix with the chosen complete
word while preserving earlier text; it does not speak immediately. The user can
continue with SPACE or finish via DONE. DONE requires nonblank text and uses the
entire spelled text as chosen intent for retrieval/candidates. Cancel discards
this Spell session and restores the unchanged intent labels, without speech.

### 13.2 Suggestions

Rank matching words from active-profile memory (people, places, things) first,
then bundled common-English lexicon, then optional context-aware LLM suggestions
when current prefix length ≥2. Deduplicate case-insensitively and return at most
three, preserving display spelling and deterministic order. LLM suggestions use
the existing bounded provider path; failure yields no invented “memory” word.

Never block letter navigation on suggestion generation. Freeze each trial's
labels: late results cannot reorder a highlighted choice. Cache suggestions for
the next eligible trial and discard stale prefix/trial responses. Speech and
learning retain the user's completed text and the ordinary grounding rules.
The lexicon, suggestion service and Spell integration are not present yet (§27).

---

## 14. Onboarding

Served at `/` when `GET /api/onboarding/status` reports `seeded: false`.

`BioWizard.tsx` shows one large textarea pre-filled with the fixture persona, so a full seed is one click on stage. The operator can edit or replace it entirely.

`POST /api/onboarding/seed`:

1. LLM call → JSON graph of nodes and edges. First pass asks for 40–60 nodes across a balanced spread of kinds; a second expansion call enriches each Person and Activity with related Things, Places and Memories. Target 150–300 nodes.
2. Validate against the pydantic seed schema; drop malformed entries rather than failing
3. Embed every node's display text
4. Insert profile, self Person, accepted nodes/edges and seed event into PostgreSQL in one transaction
5. **Stream `graph.bloom` in batches of ~10 nodes at 150 ms intervals**, so the dashboard shows the brain *growing* rather than appearing

That streaming detail is worth the twenty minutes. A graph that materialises instantly looks like a fixture; a graph that grows looks like the system learning, and it is the same data either way.

The backend owns one profile-scoped GraphService and shared database service for
its lifetime. Local graph/embedding work remains ordered on a worker; providers
and database I/O are asynchronous at the integration boundary (§10.2). Startup
loads Tiger or a valid durable mirror; profile and self Person determine identity
and onboarding status. Shutdown closes worker, database pools and journal cleanly.
REST/WebSocket snapshots and retrieval use the same accepted memory state.

Onboarding explicitly creates the `user` Person from the submitted name and
commits validated nodes and edges atomically before streaming bloom batches.
The 150-300 node target never justifies inventing facts. A valid first pass can
be used when expansion fails. Each pass has one repair within the configured
generation deadline, retaining the onboarding allowance of 4000 tokens.

The bundled fixture is an offline fallback **only for the unchanged demo name
and biography** (ignoring whitespace). Custom-biography generation failure
returns a retryable HTTP 503 and leaves the graph unchanged. Concurrent seeding
or reseeding an existing persona returns HTTP 409; replacement is not implicit.

Both rounds retrieve facts with stable IDs. Before accepting the next utterance,
learning must be remotely committed or durably journaled/applied to the mirror;
the latter is explicitly pending (§10.3). Snapshots expose updated weights and
blooms expose accepted additions. Failed writes are not announced as learned.

Reconnection restores current scan targets/highlight, intent/candidate or Spell
state, existing trial ID, grounding and fallback metadata, then FSM state. It
does not replay audio or create a new trial.

Fixture persona (`backend/data/fixtures/persona_marcus.json`):

> Marcus Alvarez, 54, a former high-school music teacher in Miami. Diagnosed with ALS three years ago; he now has no reliable speech or hand movement. His daughter Sofia visits on Sunday afternoons and he calls her "mija". His grandson Mateo is four. His wife Elena manages his care. His home nurse is Priya, who comes on weekday mornings. He has a nine-year-old beagle called Rosie who sleeps under his chair. He hates the living-room recliner because it hurts his lower back, and prefers the window seat where he can see the jacaranda tree. He used to play trumpet in a salsa band called Los Vientos. He is stubborn about not being spoken over, likes his coffee unreasonably strong, and watches Marlins games with the sound off.

Every detail exists to be retrievable and to make a generated sentence land.

---

## 15. Speech and voice

### 15.1 STT

Continuous 16 kHz mono capture via `sounddevice`. VAD via `webrtcvad` aggressiveness 2: speech start after 3 consecutive voiced 30 ms frames, end after 25 unvoiced frames (750 ms silence). On speech end the buffered segment goes to the STT provider as a batch call.

Utterances under 400 ms or transcribing to fewer than two words are discarded as noise.

**The microphone must be hard-gated while the system is speaking.** Not a flag checked later — a gate in the capture callback. Otherwise TTS output is transcribed as a partner utterance and the system talks to itself.

### 15.2 TTS and voice cloning

**Enrollment, once, before the event.** `scripts/enroll_voice.py` takes a 60 s WAV of the pilot reading a neutral passage, uploads to ElevenLabs Instant Voice Cloning, writes the voice ID to `.env`. Everyone whose voice is cloned consents explicitly.

**Runtime chain:**

1. **Cache.** SHA-256 of the sentence → `data/audio_cache/{hash}.mp3`. Hit means instant playback, zero network.
2. **ElevenLabs**, streaming. On success, write to cache.
3. **Piper.** Local ONNX, CPU, sub-100 ms. Not the cloned voice, but never silent.
4. **Browser `SpeechSynthesis`**, triggered by a WS message.

`scripts/prerender_cache.py` renders ~25 likely demo sentences before judging. **This is the highest value-per-minute work in the project** — it makes the stage demo network-independent for the lines most likely to be hit.

`conv.spoken` reports which tier served it and the measured latency, including when it was cached.

---

## 16. Frontend

### 16.1 Views and components

One frontend serves the operator dashboard and fullscreen `/pilot` (§9).
Replace old raw-waveform/PSD/target-correlation panels with:

| Component | Data and purpose |
|---|---|
| ScanPanel | Current labels/highlight and next/select meters with threshold lines |
| SpellPanel | Text, current prefix, frozen groups/suggestions and per-trial Cancel |
| MuscleStrip | Facial activity beneath next meter, contaminated next events visible |
| BandPowerPlot | Cortex sensor bands at reported units; not a raw EEG/PSD reconstruction |
| HeadsetQuality | Contact quality, battery, connection, loaded/trained profile state |
| MemoryTimeline | Actual learning events, originating conversation and pending/committed status |
| StatusBar | Provider health, next/select labels, battery, source badges and memory store; no refresh/integrity fields |

Keep Transcript, CandidatePanel, MemoryBrain, onboarding, privacy and optional
spectator views. The graph remains central; optional panels may collapse on
narrow viewports. Pilot and dashboard consume the same backend scan state;
their layouts cannot produce different target indices.

### 16.2 Existing rendering guarantees

MemoryBrain remains an imperative 3d-force-graph ref, not recreated on React
state changes. Snapshot reconciliation by stable node/edge IDs updates weights
and removes obsolete pending blooms. Traversal activation pulses the traversed
set; candidate grounding highlights only validated facts; bloom represents new
accepted memories, with pending persistence disclosed alongside the graph.

Use uPlot/ref updates for band-power/trigger diagnostics. Retire EegTrace,
PsdPlot and TargetScores rather than feeding them different units under old names.
Never display missing measurements as zero. Fallback choices stay visibly marked,
unused slots disabled, Cancel taken from the active round's cancel_idx.

### 16.3 WebSocket and input

Retain exponential reconnect (250 ms to 4 s cap), typed messages, authoritative
snapshot requests and high-rate data refs outside React state. Replace refs for
eeg.trace/eeg.psd/bci.scores with band power/trigger levels. Scan transitions and
Spell state are ordered trial-scoped UI events; drop obsolete trial deltas.

Forward n/s and 1–5 with the displayed trial ID only when keyboard input is
active; ignore global shortcuts while typing into a text field. Browser controls
must not secretly simulate BCI selections. Adding `/pilot` also requires the
audio-owner integration in §6.5, retaining existing audio unlock, stop-on-error,
disconnect and correlated playback-completion behavior.

---

## 17. Provider layer

```python
class LLMProvider(ABC):
    name: str
    @abstractmethod
    async def complete(self, system: str, user: str, *, json_mode: bool = False,
                       max_tokens: int = 400, timeout: float = 6.0) -> str: ...

class STTProvider(ABC):
    name: str
    @abstractmethod
    async def transcribe(self, pcm: bytes, sample_rate: int) -> Transcript: ...

class TTSProvider(ABC):
    name: str
    @abstractmethod
    async def synthesize(self, text: str, voice_id: str | None) -> bytes: ...

class EmbeddingProvider(ABC):
    name: str
    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray: ...
```

`registry.py` builds a `FallbackChain` per slot from env vars. Every provider is lazily constructed on first use and wrapped in a circuit breaker: three consecutive failures marks it unhealthy for 30 s and the chain skips it. An explicit rate-limit response starts cooldown immediately for at least 30 s or the provider retry delay if longer. Transient LLM HTTP 500/502/503/504 and transport failures permit one delayed retry per stage when the remaining deadline allows it; a failed or skipped retry also starts immediate cooldown. Every subsequent request receives only the remaining budget. Completion provenance is request-specific, including explicit static fallback and failure reasons. Health is reported in `sys.status`.

The final links are explicit static generation, manual text input and browser speech. The backend can boot and complete a turn without API keys; browser speech availability depends on the browser and its voices. Embeddings fall back from local MiniLM to deterministic vectors.

---

## 18. Tiger telemetry and learning history

### 18.1 Target schema

TimescaleDB hypertables use timestamp plus session/profile identifiers and
appropriate indexes/retention. Final DDL belongs in reviewed migrations, not an
in-place rewrite of an applied migration. Verify extension/version support in
the deployment and local test image before choosing policies.

| Table | Records |
|---|---|
| conversation_turns | Turn ID, profile/partner, utterance, chosen or spelled intent, spoken text, provider/tier, latency and measured cost |
| memory_events | Operation/event ID, profile, turn ID, seed/create/reinforce/dedup/purge kind, affected IDs, confidence where applicable, time and persistence state |
| band_power | Cortex sensor/band values and timestamps, source, units |
| commands | Command action/power and facial diagnostics used for trigger analysis |
| triggers | next/select role, kind, strength, contamination, original timestamp and source |
| selections | Trial/round, target, label, confidence, source, trigger, moves, cue index if cued, measured latency |
| spell_steps | Trial and turn, group/suggestion/symbol action, resulting text length, elapsed time and completion/deletion state |

Retire raw eeg_frames, correlation-score and stimulus-integrity storage from the
active ingestion path. Existing historical tables/data require an explicit
migration/retention decision, not deletion by this document. Compression targets
band_power and commands. Continuous aggregates summarize scan selections,
trigger strength/contamination and cued accuracy; retire rho_1s and refresh plots.

**memory_events is authoritative learning history**, not droppable signal
telemetry. Graph mutation and history append share a transaction/operation ID;
offline pending events are journaled with their mutation (§10.3). Enforce replay
idempotency independently of hypertable uniqueness constraints (time-partitioned
unique keys must include partition keys). A normal operation-deduplication table
can guard the complete transaction. Confidence is null for operations with no
model confidence; no invented values. Purge history retains only minimal allowed
metadata, never the deleted facts or text.

### 18.2 Nonblocking telemetry

Preserve current `TelemetryService.emit(table, record)`: bounded put_nowait,
drop on overflow, increment dropped counter, never await on the producer path.
Background batching via asyncpg uses the telemetry pool separately from memory.
Drain best-effort if unavailable; log failures with bounded frequency. Apply
signal_downsample only to stored signal diagnostics, never detector input.

Instrument actual received Cortex events and accepted scan transitions in P3;
do not fabricate data to fill a chart. No live producers call the current sink
yet, and current analytics is a stub (§27). This wiring is required future work.

### 18.3 Analytics and timeline

Publish analytics.summary every 2 s from recorded data:

- selections_total and measured mean_selection_latency_s;
- mean_moves_per_selection, using accepted next events for the trial;
- false_selects_per_min **only** during explicitly annotated no-select/control
  periods; normal conversation cannot establish intended versus false selects;
- contaminated_next_pct over next events with valid facial diagnostics;
- letters_per_min from accepted text and measured spelling time, accounting for
  deletion; suggestions distinguished from manually selected characters;
- accuracy_pct and cued_trials from cue-versus-selection outcomes in cued blocks.

Remove mean_rho_by_target and old correlation drift; do not relabel them as
mental-command scores. Unmeasured metrics return null/unavailable, not zero.
ITR must not reuse fixed-five-target SSVEP assumptions: report only with an
explicit measured scan protocol, trial target counts and elapsed time; otherwise
null. Dashboard MemoryTimeline reads `/api/memory/timeline?since=` and distinguishes
learned/updated facts, originating turn, confidence, pending and committed state.

---

## 19. Spectator relay

Preserve outbound-only connection from the pilot PC to the relay and then judge
phones; no commands or training from that stream may enter P1/P3. The optional
DigitalOcean relay/domain remains independent of the core turn path.

Send sanitized highlight/selection and public label, spoken lines/approved
transcript, aggregate node/edge counts, source badge and trigger-modality labels,
at the existing throttle. Remove correlation/refresh/profile/frame-drop fields.
Do not send Cortex packets/band-power arrays, personal graph content, embeddings,
credentials or private profile IDs. The restriction is on spectator export;
it is not a claim that Tiger Cloud never stores personal memory (§20).

Gradient remains the configured third LLM provider via the existing
OpenAI-compatible adapter. No provider-chain change follows from this migration.

---

## 20. Data and privacy

The storage migration changes where personal data lives. Tiger Cloud contains
profile, biography, memory graph, conversations and learning history; a durable
local mirror/journal retains recovery copies. A deliberately configured local
PostgreSQL deployment has a different destination and must be labeled accurately.
Cortex/Emotiv data handling also needs disclosure; local WebSocket transport is
not proof that every vendor operation stays on-device.

The privacy ledger must distinguish database synchronization, LLM facts/prompts,
STT audio, TTS sentence text, consented voice enrollment and sanitized spectator
traffic. Remove claims that the graph or enrollment audio “never leaves this
machine”. Display only recorded activity; the empty ledger remains **No outbound
activity recorded.** Database migrations must not silently enable spectator graph
export. Costs use actual measured usage/configured prices, not invented totals.

Automatic fallbacks remain as implemented; there is no manual offline-mode
switch, telemetry-routing toggle or restriction on browser voices.

Purge scope graph removes active-profile memory remotely and from mirror/journal;
telemetry removes applicable session records; all also clears conversation/history
content and audio cache as specified by the approved retention policy. Confirm
destructive purge through the existing UI. Prevent outbox resurrection (§10.3).
Report queued remote deletion as pending until confirmed. The current endpoint
only clears audio cache for all; real memory/telemetry purge is future work (§27).

---

## 21. Build and migration plan

### 21.1 Coordination

Dev A owns application/input integration and contracts; Dev B owns Cortex bridge,
detectors/training/recording; Dev C owns pilot/dashboard views; Dev D owns graph,
retrieval, prompts and Spell service. Coordinate the Spell service/FSM boundary
and database facade explicitly. This document does not authorize edits to others'
paths or the frozen interfaces; follow AGENTS.md when implementing.

### 21.2 Sequence

1. Preserve the tested memory/provider baseline (already merged locally on main).
2. Review this architecture-only revision, including adjustments in §27.
3. Approve one coordinated config/schema revision with Python models, frontend
   types and documentation. Include new browser trial/state semantics and retire
   old unions/settings together; do not leave incompatible processes running.
4. Implement shared scan/keyboard/replay, then merge teammate P1/BCI and pilot
   work after reviewing its actual diff. Retire stimulus references. Training and
   scan acceptance must pass with deterministic streams before headset use.
5. Integrate binary Spell/suggestions/FSM and dual-view playback, then verify one
   ordinary and one spelled end-to-end turn, Cancel and reconnection.
6. Port Tiger memory/db service with transactional seed, migration, mirror/outbox
   and real-database two-turn/restart/outage tests before retiring Kuzu.
7. Wire telemetry/analytics/timeline and verify headset cued/idle tests before
   making live demo or sponsor claims. Rehearse on the single target PC.

Use short-lived branches and tested Conventional Commits. Preserve untracked
data and existing personal stores. Do not push automatically. If teammate changes
conflict ambiguously, coordinate rather than guessing. This revision changes
only ARCHITECTURE.md; stages 3–7 are not implemented by it.

### 21.3 Critical path and cut order

Contracts → shared scan + synthetic streams → Cortex/training + pilot → ordinary
and spelled turns → Tiger migration/outage safety → headset validation.

If time is constrained, cut in this order: LLM word suggestions; spectator;
optional privacy UI (not integrity/disclosure); MemoryTimeline; new fact extraction
(keep reinforcement); automatic partner identification (explicit known-person
override); onboarding wizard (only the disclosed unchanged demo fixture).
No Local Mode feature exists to cut. Preserve already working features unless a
separate scope decision requires a cut.

**Never cut:** real next/select path, idle behavior, Spell's letter path, memory
brain, consented voice output, Tiger memory persistence and truthful input/storage
disclosure. No claims based on features removed from the delivered build.

---

## 22. Failure modes

| Failure | Detection | Response |
|---|---|---|
| Cortex/Launcher unavailable or approval denied | Connection/auth error | Show disconnected; no live triggers; explicit keyboard/replay only |
| Profile missing/untrained | profile_loaded/trained_actions | Load/retrain; do not arm |
| Poor contact, missing/stale samples | Quality/freshness status | Reset holds, disarm until valid; show missing data |
| Next/select never fires or fires spontaneously | Level/hold logs and cued/control trials | Tune min_power/hold_s, retrain; repeat headset acceptance, never assert success |
| Facial contamination of next | contaminated flag | Show muscle strip/flag, record and assess; no pure-neural claim |
| Simultaneous/held actions | Detector/refractory state | Single select at pre-event highlight; release before rearm |
| Wrong GPU, sluggish browser | Measured UI performance | Select NVIDIA; no fake refresh/classification metric |
| Pilot disconnect/stale UI | WS and trial IDs | Disable input; restore authoritative state on reconnect |
| Tiger read fails | Bounded query error/timeout | Valid mirror; mark store state; no fixture substitution for custom identity |
| Tiger write fails or commit result uncertain | Deadline/DB error | Durable idempotent outbox, explicitly pending; next turn reads accepted mirror |
| Local journal fails too | Persistence error | Report learning unavailable; no success bloom or unpersisted memory acceptance |
| Telemetry overflow/DB unavailable | Drop count/errors | Drop diagnostics, never memory operations or detector samples |
| Late LLM suggestion | Prefix/trial mismatch | Discard; frozen labels and letter path continue |
| LLM timeout/429/transient failure | Existing deadline/cooldown metadata | Existing bounded chains; visible intent-preserving fallback |
| STT/TTS failure | Provider failure | Existing Whisper/manual or Piper/browser chain; report playback failure honestly |
| Missing playback acknowledgment | Reply ID/recipient/deadline | Keep microphone gated as implemented; no self-talk loop |
| Duplicate extraction | Similarity/node count | Existing dedup/cap, investigate; never silently duplicate on outbox replay |
| Spectator unavailable | Connection error | Hide link; zero selection/turn impact |
| Live headset demo fails | Failed validation/runtime failure | Disclosed recorded replay, then backup video; state actual failure, not invented causes |

---

## 23. Acceptance tests

These are target gates, **not claims of tests already passing**. Retain the
existing provider recovery, memory pipeline, playback and privacy regressions.

| Gate | Pass criterion |
|---|---|
| T1 Detectors | Every scripted next/select hold detected once; none during two minutes of deterministic baseline noise; verify gaps, release, refractory, poor contact, simultaneous actions and contamination |
| T2 Scan | Wrap enabled tiles; no automatic movement; correct dynamic Cancel for intent/candidate/6-tile Spell; stale/duplicate events rejected; timeout closes trial |
| T3 Speller | Every alphabet/special symbol reachable; DELETE/SPACE/DONE correct; nonblank DONE → candidate generation, Cancel → original intent labels |
| T4 Suggestions | Memory → lexicon → optional LLM ranking/dedup; stale responses cannot reorder active tiles; no LLM still permits full letter path |
| T5 App integration | Real REST/WS keyboard next/select completes ordinary and spelled turns, including selected-intent fallback, grounding, speech and learning |
| T6 Headset go/no-go | **20 cued selections ≥90% correct; ≤1 unintended select in a measured 2-minute no-select block**; report actual results before demo |
| T7 Training/replay | Confirmed neutral/push training saved/reloaded; recorded streams reproduce detector/scan outcomes with source badges |
| T8 Tiger memory | Real local TimescaleDB+pgvector: custom seed → both retrieval rounds with IDs → reply/reinforcement/new fact → next-turn retrieval; restart retains identity/snapshot/learning |
| T9 Seed/migration | Invalid entries dropped, seed rollback, duplicate/concurrent seed 409, custom failure 503 without demo substitution; existing IDs/weights/facts survive Kuzu import |
| T10 Outage/restart | Turn reads mirror when Tiger fails; pending durable write retrievable next turn; restart replays journal; outbox drains once even after ambiguous remote commit |
| T11 Purge | No old queued operation resurrects deleted data; pending versus confirmed remote deletion distinguished |
| T12 Playback/reconnect | Existing acknowledgment/mic gate preserved with pilot+dashboard; no duplicate audio; reconnect restores trial/highlight/Spell state without replaying speech |
| T13 Telemetry | Existing bounded-queue nonblocking test retained; real ingestion/aggregate counts match events; missing measurements remain unavailable |
| T14 Privacy/spectator | Correct source/modality/store badges; no raw Cortex/personal graph/credential spectator export; no manual offline endpoint or switch |
| T15 Delivery | Full pytest, Ruff lint/format, frontend tests/build; browser and target-PC rehearsal; report unavailable hardware/cloud checks |

Retire stimulus-refresh, FBCCA accuracy, harmonic-profile and eTRCA tests from the
active acceptance plan. Those modules/tests are absent in this checkout; do not
pretend deleting them here completes the migration. Replace existing fake-sensor
and SSVEP-contract tests with equivalent trigger/scan coverage during implementation.
Automated tests require no real credentials, headset or model download; real DB
integration uses an isolated local service/container and must be a release gate,
not silently skipped when unavailable.

---

## 24. Assumptions and unresolved deployment checks

| Item | Required check |
|---|---|
| EPOC X free-tier streams | Confirm actual account/profile availability and Cortex field/timestamp schemas before coding adapter |
| Trigger thresholds | Initial values only; tune and meet T6, including fatigue/false selects |
| One-PC layout/GPU | Fullscreen pilot and usable operator view; validate actual rendering, not reported OS refresh |
| Training | Neutral/push saved to active pilot profile; no assumption that sample counts alone yield readiness |
| Tiger deployment | Extensions supported, DSN configured, migration and restart verified; local PG is explicit dev/test backing, not hidden remote success |
| Mirror/outbox | Durable bounded operational design and idempotency proven; unavailable journal cannot claim learning |
| Voice | Existing configured voice/fallbacks preserved; enrollment consent and availability verified separately |
| Persona | Marcus is only the unchanged demo fallback; custom biography never replaced |
| Evidence | Teammate measurements are reported evidence; next/select headset test remains outstanding |

---

## 25. Credits and prior art

- Credit Zahid's headset experiments, review notes and proposed Cortex/step-scan
  design (2026-09-27); preserve source experiment history when merged.
- Lucid Voice remains prior art for provider abstraction, graceful degradation,
  cache-first speech and candidate selection; no new copying claim is implied.
- Facility-location submodular selection: retain original algorithm attribution;
  current implementation is NumPy. apricot profiling motivated that choice.
- FBCCA/TRCA, BrainFlow, PsychoPy and LSL belong to retired-design history, not
  claims about the delivered scanning path. Kuzu remains migration history until
  its port is complete; installed dependencies are not proof of active use.
- Active/target technologies include Cortex/Emotiv, PostgreSQL, TimescaleDB,
  pgvector, NumPy, sentence-transformers, FastAPI, uvicorn, pydantic, PyZMQ,
  asyncpg, React/Vite/Tailwind, 3d-force-graph/three.js/uPlot, sounddevice/VAD,
  Piper/faster-whisper and the existing cloud providers.

---

## 26. Submission notes

Describe only measured, delivered behavior. Remove flicker-grid, raw-EEG-rate,
per-target-correlation and fixed communication-speed claims from future pitches.

| Track | Accurate target story, once implemented |
|---|---|
| Microsoft | Step-scanned semantic choices plus accessible spelling and a personal memory graph |
| ElevenLabs | Consented voice restoration with disclosed cache/local/browser fallbacks |
| Gemini | Grounded intents/candidates, partner ID, extraction and onboarding under bounded JSON/recovery contracts |
| Tiger Data | Unified persistent personal memory and learning timeline plus real Cortex/scan telemetry; transactional writes and demonstrated outage recovery |
| DigitalOcean / GoDaddy | Sanitized outbound spectator relay/domain; configured Gradient alternative |
| Assurant | Truthful data destinations, measured costs, effective purge and explicit fallback/store state |

Use the exact mental-command/jaw-clench wording in DEMO-6. A cloud database
schema, placeholder analytics or recorded replay must not be pitched as completed
live integration. Remove tracks whose components are not actually delivered.

---

## 27. Implementation migration inventory (documentation-only review)

Inspected baseline: local `main` **a5ee13c**, after memory and provider-resilience
merges. Only ARCHITECTURE.md is edited by this revision. “Implemented” below means
present in that checkout, not a claim about hardware teammate branches.

### 27.1 Already implemented files that must change

| Existing files | Current implementation | Required adaptation |
|---|---|---|
| `shared/schemas.py`, `shared/config.py`, `config.yaml`, `.env.example`, `frontend/src/lib/types.ts` | Raw-EEG/SSVEP/stimulus unions; fixed 4/5 targets; four intents; Kuzu path; TIMESCALE_DSN; playback acknowledgment | Coordinated §5–§6 contract revision, dynamic scan/Spell/source/status/analytics models and DSNs; retain playback and fallback metadata |
| `inputs/base.py`, `inputs/keyboard.py` | Fixed n_targets, numeric direct pick, inactive-slot rejection, one Selection per trial | Current-label counts, shared ScanController, n/s and trial-stamped keyboard events, six-tile Spell support |
| `inputs/ssvep.py`, `inputs/replay.py` | Real ZMQ adapter for SensorSelection/ShowTargets; ReplayInput inherits SsvepInput | Replace with BCI TriggerEvent mapping and Cortex replay; remove stimulus socket ownership |
| `backend/app/main.py` | Real app lifecycle, build_input(keyboard/ssvep/replay), Kuzu/worker setup, status, mode endpoint, input hot-swap; cued-block endpoint is a stub | Build bci, own sensor-control publisher, wire scan/status, training/cued APIs, Tiger pools/mirror/outbox, suggestions/timeline; remove mode/train_etrca/stimulus settings |
| `backend/app/orchestrator.py` | Working conversation/grounding/writeback/reconnect; Cancel padded to last fixed physical slot; old SPELLER_WAIT loop; 30 s wait; keyboard stimulus publisher | Per-round Cancel and counts, three intents+Spell, SPELLING/DONE→candidates, configurable scan timeout, scan state restoration, durable/pending learning; remove old stimulus path |
| `backend/app/services/speller.py`, `interfaces.py` | N-ary `options/descend/commit`, default four, hardcoded alphabetical symbols and SPEAK; internal protocol expects reset/root_labels/next_labels/spelled_text instead | Reconcile actual service/protocol before wiring; config binary alphabet, text buffer/specials, ranked suggestions, DONE intent behavior |
| `backend/prompts/intent_labels.txt`, `candidates.txt`, `services/generation.py` | Four-label prompt/parser; grounded candidate IDs, shared recovery, exact-intent fallback | Three-label prompt/parser/static labels; app-owned Spell/Cancel; spelled-text prompt clause; preserve grounding and request-specific fallback metadata |
| `backend/app/ws.py` | Relays EEG/PSD/scores, ignores sensor status there; input keys and matching playback acks; audio broadcast to all clients | Relay band power/levels/triggers/status, trial checks, scan/Spell reconnect, audio-owner integration for dual views; preserve ack safety |
| `services/graph.py` | Real Kuzu schema/CRUD/Cypher, NumPy vector cache, transactions, reinforcement, get_node/edges_among/get_embeddings/close | Profile-scoped Tiger tables/queries, constraint and ID parity, durable mirror/outbox, ordered operations and lifecycle; verified data migration |
| `services/worker.py`, `onboarding.py`, `extraction.py`, `partner.py`, `retrieval.py` | Serialized graph/embedding work, atomic Kuzu seed/extraction, correct Memory text mapping, partner checks, two-round retrieval, NumPy selection | Reconcile DB async boundary, remote/pending commits and snapshot/cache invalidation; preserve thresholds/dedup/identity; keep NumPy algorithm |
| `services/telemetry.py`, `analytics.py`, `migrations/001_timescale.sql` | Bounded async writer exists but no runtime emit producers; old EEG/score tables; analytics returns zeros/nulls stub | Real Cortex/scan emit wiring, separate pools, safe schema upgrade, measured aggregates; non-droppable transactional learning history |
| `frontend/src/App.tsx`, `views/Dashboard.tsx`, `lib/{ws,api,streams,types}.ts`, `components/CandidatePanel.tsx` | Working reconnect/snapshots, refs for EEG/PSD/scores, keys 1–5, padded choices, fallback notice, audio playback | /pilot routing, authoritative scan/Spell state, n/s/trial IDs, dynamic Cancel, new streams/APIs, shared choice renderer and audio-owner behavior |
| `components/{EegTrace,PsdPlot,TargetScores,StatusBar,SessionAnalytics}.tsx`, `lib/plots.ts` | Real old-signal plots, configured decision thresholds, refresh placeholders; stub-backed analytics UI | Replace old plots with ScanPanel/MuscleStrip/BandPowerPlot/HeadsetQuality/SpellPanel; trigger/battery/source status; measured scan metrics |
| `components/MemoryBrain.tsx`, `lib/{brain,memory}.ts`, onboarding/PrivacyPanel | Authoritative ID/weight snapshots, grounding/bloom/reconnect; custom seed error display; privacy UI without offline toggle | Preserve graph rendering semantics; display pending store/learning status and add MemoryTimeline; accurate Tiger destination/purge results |
| `services/spectator.py`, `services/cost.py`, privacy routes/UI | Spectator connector stub, partial outbound instrumentation/cost tracking; purge only clears cache for all | Keep relay boundaries, use scan payloads; instrument actual database/cloud flows; implement real purge separately with outbox safety |
| `run.sh`, `scripts/fake_sensor.py`, dependency manifests | Launcher references missing sensor/stimulus; fake_sensor actually emits legacy score/selection frames; Kuzu dependency present | Drop P2 launch, order Cortex readiness/pilot start, replace fake stream with real-detector fixtures; review DB/Cortex dependencies and locks together, CPU-only |
| Existing Python/frontend tests | Kuzu two-turn/restart tests, selection/Cancel/switching, grounding/dedup/rollback, playback, retries, snapshot and score UI tests | Port real-DB fixtures, add scan/Spell/detector/outbox tests; update retired contract/target-count assertions without losing regression coverage (§23) |

Paths prefixed `services/` in this table are under `backend/app/services/`;
`components/` and `lib/` are under `frontend/src/`.

Concrete regression files affected include `tests/test_schemas.py`,
`test_inputs.py`, `test_fake_sensor.py`, `test_orchestrator.py`,
`test_generation.py`, `test_generation_integration.py`, `test_speller.py`,
`test_graph.py`, `test_memory_services.py`, `test_memory_pipeline.py`,
`test_onboarding.py`, `test_extraction.py`, `test_retrieval.py`, and
`test_telemetry.py`; frontend `tests/{scores,memory,playback,fallbacks}.test.mjs`
must retain or adapt their guarantees. Preserve provider-resilience/rate-limit
tests unchanged unless the implementation touches that boundary.

### 27.2 New work, not “already implemented parts to update”

This checkout has **no sensor/ or stimulus/ directories**, no inputs/bci.py or
inputs/scan.py, no inputs/emotiv.py, no `/pilot`, Cortex client/detectors/training,
lexicon/suggestion service, db.py/mirror/outbox, MemoryTimeline or new migrations.
It also lacks scripts/check_stimulus.py and DSP/FBCCA/profile tests. Their names
in the old architecture or teammate notes do not establish local implementation.
The experiment directory is reported elsewhere, not verified in this checkout.

### 27.3 Corrections to the supplied review notes

- **Grounding is connected:** candidate prompts carry stable fact IDs, unknown
  grounding is removed, UI highlights actual IDs, selected nodes/edges reinforce.
  Empty grounding is intentional for the new exact-intent fallback.
- **Seeding is already transactional in Kuzu**, with rollback tests. Preserve that
  guarantee in PostgreSQL; “skip the seeding fix” is obsolete advice.
- **Playback gating is implemented** through correlated browser completion. Do
  not regress it; adding a second browser view requires recipient/audio ownership.
- **Adapter hot-swap already restarts the listener and rolls back on failure.**
  Adapt it to bci/scan instead of treating it as missing.
- **Cancel at fixed last physical target is currently intentional and tested.**
  The new variable-round scheme is a contract change, not merely a bug fix.
- **Score thresholds now come from backend config**, not hardcoded UI numbers;
  retiring TargetScores still requires replacing its data/visibility guarantees.
- **Partner/extraction already use configured generation budgets** and the shared
  retry/repair path. Keep it. NumPy facility location also already exists.
- **Tiger is not the current memory store:** it is accepted target architecture;
  Kuzu remains real runtime storage and Tiger telemetry ingestion is disconnected.
- **Speller exists as a tree service but is not wired into create_app**, and its
  protocol differs from the old FSM expectations. New Spell is substantial work.
- **Local Mode was removed** with its endpoint/config/status; the proposed cut
  list must not reintroduce it. Other privacy functionality is preserved in scope.

### 27.4 How the proposals were incorporated

| Proposal items | Architecture disposition |
|---|---|
| A1–A5, A9, A14 | Adopt Emotiv, no flicker, backend-owned two-switch scan and browser pilot; add stale/release/quality rules and preserve honest source labels |
| A6, A12 | Adopt binary Spell as a real intent path; clarify six tiles, suggestion freeze, DONE versus suggestion completion and current service mismatch |
| A7–A8 | Adopt target config/contracts, **defer all implementation**; add explicit n=2, durable mirror path, freshness/training duration and trial IDs; preserve playback/fallback metadata |
| A10 | Adopt Tiger memory/telemetry target; add profile isolation, transactional history, durable/idempotent outbox and truthful pending state; do not bypass existing seed guarantees |
| A11 | Accept NumPy; documentation catches up with code, no algorithm rewrite |
| A13 | Adopt new panels while retaining graph/reconnect/playback behavior |
| A15 | Replace old gates/cut plan; do not restore Local Mode, fabricate partner identity, or claim unrun headset/DB tests |
| A16 | Adopt target layout; distinguish absent modules and teammate-branch claims from existing files; preserve historical data/migrations |

Before implementation, finalize the audio-owning browser handshake and Cortex
training response mapping in the coordinated contract review, and validate
mirror/journal durability and deployment permissions. This document specifies
the required outcomes; it does not claim these integrations already work.
