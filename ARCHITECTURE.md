# ARCHITECTURE

**Flick — a semantic brain–computer interface for assistive communication.**

This document is the single source of truth for the system. Numeric constants are normative; where a constant is tunable it lives in `config.yaml` (§5) and code reads it from there. No magic numbers in source.

---

## 0. How to read this

- §1–§3 define what is being built and how the processes fit together.
- §4–§6 are the contracts: repository layout, configuration, and every message schema. **These are frozen first and everything else depends on them.**
- §7 is the input abstraction. Read it before writing any code that consumes a user selection.
- §8–§20 specify each subsystem.
- §21–§26 cover build sequencing, failure handling, acceptance criteria and submission.

---

## 1. Product definition

### 1.1 What it does

A person who cannot speak wears an EEG headset and looks at a screen showing five flickering tiles. A microphone listens to whoever is talking to them. When the conversational partner speaks, speech-to-text transcribes it, and a language model — grounded in a personal knowledge graph of the user's life — writes four candidate *intents* onto the tiles.

The user selects one by looking at it. Their visual cortex entrains to that tile's flicker frequency; the signal-processing layer detects which. The system then retrieves relevant personal facts from the graph, generates three full candidate sentences, and displays them for a second selection. The chosen sentence is spoken aloud in a clone of the user's own voice. Afterwards the system extracts new facts from the exchange and grows the memory graph, rendered live in 3D so observers can watch it think and learn.

### 1.2 Why it is not a speller

Character-by-character BCI spelling runs at roughly 8 words per minute against speech's 150. Selecting *semantic intent* rather than letters produces a full sentence in about four seconds. The Speller mode exists as a deliberate contrast so the difference can be demonstrated rather than asserted.

### 1.3 Modes

| Mode | Purpose | Priority |
|---|---|---|
| **Intent** | The product. Semantic selection, ~4 s per sentence. | P0 |
| **Speller** | N-ary search over the alphabet, ~6 s per character. Shown briefly to make the contrast visible. | P2 |

### 1.4 Non-goals

Not built, not specified: VR stimulus delivery, haptic feedback, relay or environmental control, Raspberry Pi involvement, EMG hybrid confirmation on the OpenBCI path, local neural voice cloning, speaker identification by voice embedding, multilingual output, blockchain.

### 1.5 Sponsor alignment

Each integration is load-bearing. Nothing is included solely to claim a track.

| Track | What the system uses it for | Priority |
|---|---|---|
| Best Overall | Automatic | — |
| **Microsoft — What's Missing?** | The interface is a flicker grid and a 3D memory graph. There is no chat window anywhere in the product; AI is one stage of a pipeline, not the experience. | P0 (framing only) |
| **ElevenLabs** | Instant voice cloning; the user's restored voice (§16) | P0 |
| **Gemini** | Intent labels, grounded sentences, partner identification, fact extraction, graph seeding (§13) | P0 |
| **Tiger Data** | Time-series sink for EEG, correlation scores and stimulus integrity; continuous aggregates drive the analytics panel (§18) | P1 |
| **DigitalOcean** | Spectator relay droplet; Gradient AI as third LLM fallback (§19) | P2 |
| **GoDaddy Registry** | Domain fronting the spectator view | P2 |
| **Assurant** | Data-flow ledger, per-turn API cost, one-click fully-local mode (§20) | P3 |

---

## 2. Decision register

Deviating from any of these requires editing this document first.

### 2.1 Hardware

| ID | Decision |
|---|---|
| HW-1 | **OpenBCI Cyton, 8 channels, 250 Hz.** The Daisy module is not used. |
| HW-2 | Montage: **O1, Oz, O2, POz, PO3, PO4, Pz, CPz**; SRB and BIAS on earlobe clips A1/A2. |
| HW-3 | Wet gel electrodes. Budget 25 minutes for application. |
| HW-4 | The Cyton runs on **battery power only**. Never USB-powered during recording. |
| HW-5 | Stimulus renders on Machine A's built-in panel. Judge dashboard on Machine B. |
| HW-6 | Emotiv headsets are a **secondary, optional input path** (§7.5), never the primary. |

### 2.2 Interaction

| ID | Decision |
|---|---|
| UX-1 | Two-round selection: intent → three candidates → speak. |
| UX-2 | **Five targets.** Four semantic, one Cancel. Reducible to 4+cancel by config. |
| UX-3 | Frequencies are **profile-dependent**, auto-selected from measured refresh rate (§9.2). |
| UX-4 | The idle state is real. Below threshold, nothing is selected. |
| UX-5 | Confirmation by dwell: three consecutive agreeing windows. No hybrid signal. |
| UX-6 | Partner identity inferred by LLM from transcript, with manual override. |
| UX-7 | English only. |

### 2.3 Signal processing

| ID | Decision |
|---|---|
| DSP-1 | Window length is profile-dependent. Hop is 250 ms on both profiles. |
| DSP-2 | Notch 60 Hz (Q=30), then 4th-order Butterworth bandpass, zero-phase. |
| DSP-3 | **FBCCA** is the default classifier. Five sub-bands, three harmonics. |
| DSP-4 | **eTRCA** is used automatically when a calibration file exists for the active pilot and is under two hours old. Not surfaced in the UI. |
| DSP-5 | Stimulus onset markers are published over LSL for calibration alignment. |
| DSP-6 | **Nothing classifies until it has received a `stim.profile` message.** |

### 2.4 Software

| ID | Decision |
|---|---|
| SW-1 | Python 3.11, `uv`. |
| SW-2 | Backend FastAPI + uvicorn. Frontend Vite + React + TypeScript + Tailwind. |
| SW-3 | Graph: KuzuDB, embedded. |
| SW-4 | Embeddings: `all-MiniLM-L6-v2` (384-dim), local, CPU, stored as a Kuzu property. |
| SW-5 | Context curation: `apricot-select`, facility location, greedy. |
| SW-6 | LLM: Gemini primary, provider-swappable. |
| SW-7 | STT: cloud primary, `faster-whisper small` on CPU as fallback. |
| SW-8 | TTS: ElevenLabs primary, Piper local fallback, pre-rendered cache in front of both. |
| SW-9 | **The entire Python stack is CPU-only.** No CUDA dependency anywhere. |
| SW-10 | Memory writeback: LLM auto-extracts facts after each turn, commits above threshold, blooms onto the graph. No decay pass. |
| SW-11 | Persona is created at runtime through an onboarding wizard. A committed fixture exists as fallback. |
| SW-12 | Three OS processes plus the frontend dev server. ZeroMQ between them. |
| SW-13 | Every provider and service is lazily constructed and degrades to a correctly-shaped placeholder. |
| SW-14 | TimescaleDB is the telemetry sink and is **never on the critical path**. |
| SW-15 | The spectator relay connection is **outbound only**; nothing from it enters the pipeline. |
| SW-16 | A Local Mode switch forces the fully-offline chain. The system must remain functional with it on. |

### 2.5 Demo integrity

| ID | Decision |
|---|---|
| DEMO-1 | **No hidden manual triggering of classifications.** Ever. |
| DEMO-2 | Replay mode plays a real recorded session through the real classifier, with a persistent on-screen `REPLAY` badge. |
| DEMO-3 | Every non-brain input adapter displays a persistent badge naming what it is. |
| DEMO-4 | A scripted-prompt key exists for feeding partner utterances when the room is too loud for STT. It bypasses the microphone only, never the classifier. |
| DEMO-5 | Every session is recorded to disk automatically. |

---

## 3. Topology

### 3.1 Machines

```
┌───────────────────────────────────────────────────────────────┐
│ MACHINE A                                                     │
│   USB ── OpenBCI Cyton dongle                                 │
│                                                               │
│   P1  sensor     acquisition + DSP + classification           │
│   P2  stimulus   vsync-locked flicker, fullscreen             │
│   P3  backend    FastAPI, orchestrator, graph, providers      │
│   P4  frontend   Vite dev server                              │
└──────────────────────────┬────────────────────────────────────┘
                           │ WebSocket over a DIRECT link
                           │ (ethernet or dedicated hotspot —
                           │  never venue wifi)
┌──────────────────────────▼────────────────────────────────────┐
│ MACHINE B — judge dashboard, browser only                     │
└───────────────────────────────────────────────────────────────┘
```

The pilot sees only the P2 stimulus window. Judges see only the Machine B dashboard.

### 3.2 Processes

| Process | Entry point | Binds | Connects to |
|---|---|---|---|
| **P1 sensor** | `python -m sensor.main` | ZMQ PUB `tcp://127.0.0.1:5555` | ZMQ SUB `5556` |
| **P2 stimulus** | `python -m stimulus.main` | ZMQ PUB `5557`, LSL outlet `Flick-Markers` | ZMQ SUB `5556` |
| **P3 backend** | `uvicorn backend.app.main:app --host 0.0.0.0 --port 8000` | HTTP/WS `:8000`, ZMQ PUB `5556` | ZMQ SUB `5555`, `5557` |
| **P4 frontend** | `npm run dev` | HTTP `:5173`, proxies `/api` and `/ws` to `:8000` | — |

Model loading, LLM calls and TTS synthesis all block for seconds at a time. The sensor loop never shares a process with them.

### 3.3 One turn, end to end

```
partner speaks
  ├─► [P3] VAD → STT → transcript
  ├─► [P3] LLM: identify partner from transcript + known Person nodes
  ├─► [P3] retrieval: embed → 2-hop expand → submodular select
  ├─► [P3] LLM: four intent labels
  ├─► [P3] ZMQ: show_targets ──► [P2] renders tiles
  │         WS: conv.intents ──► dashboard
  ├─► [P2] LSL marker: trial onset
  ├─► [P1] windows every 250 ms → classifier → scores ──► dashboard
  ├─► [P1] three agreeing windows → Selection
  ├─► [P3] retrieval round 2 → LLM: three candidate sentences
  │         WS: graph.activate ──► nodes pulse
  ├─► [P1] second Selection
  ├─► [P3] TTS (cache → ElevenLabs → Piper) → audio
  └─► [P3] LLM: fact extraction → graph writeback → graph.bloom
```

---

## 4. Repository layout

```
flick/
├── ARCHITECTURE.md
├── AGENTS.md
├── README.md
├── CREDITS.md
├── pyproject.toml              # uv, python = "3.11"
├── uv.lock
├── config.yaml
├── .env.example
├── run.sh                      # launches P1..P4
│
├── shared/
│   ├── schemas.py              # pydantic models for EVERY message (§6)
│   ├── config.py               # pydantic-settings loader
│   ├── bus.py                  # ZMQ PUB/SUB wrappers
│   └── logging.py              # structlog, JSON to stdout + rotating file
│
├── inputs/                     # §7 — the selection abstraction
│   ├── base.py                 # InputSource ABC
│   ├── keyboard.py             # DEV: number keys. No hardware at all.
│   ├── ssvep.py                # production: consumes P1 over ZMQ
│   ├── replay.py               # recorded session through the real classifier
│   └── emotiv.py               # optional, see §7.5
│
├── sensor/                     # P1
│   ├── main.py
│   ├── sources/
│   │   ├── base.py             # EEGSource ABC
│   │   ├── cyton.py            # BrainFlow
│   │   ├── synthetic.py        # generates solvable SSVEP (§8.4)
│   │   └── replay.py           # .npz at real-time pace
│   ├── dsp.py
│   ├── classifiers/
│   │   ├── base.py
│   │   ├── fbcca.py
│   │   └── etrca.py
│   ├── decision.py             # threshold + margin + dwell + refractory
│   ├── calibration.py
│   └── recorder.py
│
├── stimulus/                   # P2
│   ├── main.py
│   ├── profile.py              # measure refresh → select hi/lo (§9.2)
│   ├── tiles.py
│   ├── markers.py              # LSL
│   └── integrity.py
│
├── backend/                    # P3
│   ├── app/
│   │   ├── main.py
│   │   ├── orchestrator.py     # conversation FSM (§14)
│   │   ├── ws.py
│   │   └── services/
│   │       ├── graph.py
│   │       ├── retrieval.py
│   │       ├── generation.py
│   │       ├── extraction.py
│   │       ├── partner.py
│   │       ├── onboarding.py
│   │       ├── speech.py
│   │       ├── voice.py
│   │       ├── speller.py
│   │       ├── telemetry.py
│   │       ├── analytics.py
│   │       ├── spectator.py
│   │       └── cost.py
│   ├── providers/
│   │   ├── base.py
│   │   ├── llm_gemini.py
│   │   ├── llm_openai_compat.py    # OpenAI, LM Studio, Ollama, DO Gradient
│   │   ├── stt_deepgram.py
│   │   ├── stt_faster_whisper.py
│   │   ├── tts_elevenlabs.py
│   │   ├── tts_piper.py
│   │   ├── embed_minilm.py
│   │   └── registry.py         # env → instance, with fallback chains
│   ├── prompts/
│   │   ├── intent_labels.txt
│   │   ├── candidates.txt
│   │   ├── extraction.txt
│   │   ├── partner_id.txt
│   │   └── onboarding_seed.txt
│   └── data/
│       ├── fixtures/persona_marcus.json
│       └── audio_cache/
│
├── frontend/
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── lib/{ws.ts,api.ts,types.ts}
│       ├── views/{Dashboard.tsx,Onboarding.tsx}
│       └── components/
│           ├── MemoryBrain.tsx      # 3d-force-graph
│           ├── EegTrace.tsx         # uPlot
│           ├── PsdPlot.tsx          # uPlot
│           ├── TargetScores.tsx
│           ├── Transcript.tsx
│           ├── CandidatePanel.tsx
│           ├── StatusBar.tsx
│           ├── SessionAnalytics.tsx
│           ├── PrivacyPanel.tsx
│           ├── SpectatorQR.tsx
│           └── BioWizard.tsx
│
├── spectator/                  # deployed to DigitalOcean, not Machine A
│   ├── relay.py
│   ├── static/index.html
│   └── Dockerfile
│
├── migrations/001_timescale.sql
│
├── scripts/
│   ├── enroll_voice.py
│   ├── prerender_cache.py
│   ├── run_calibration.py
│   ├── check_stimulus.py
│   ├── seed_timescale.py
│   └── smoke_machine_a.py
│
└── tests/
    ├── test_schemas.py
    ├── test_dsp.py
    ├── test_fbcca.py
    ├── test_profiles.py
    ├── test_decision.py
    ├── test_inputs.py
    ├── test_graph.py
    ├── test_retrieval.py
    └── test_telemetry.py
```

---

## 5. Configuration

`config.yaml`, loaded by `shared/config.py`. Secrets live in `.env` and never in `config.yaml`.

```yaml
input:
  adapter: keyboard          # keyboard | ssvep | replay | emotiv
  replay_file: null

mode:
  source: synthetic          # cyton | synthetic | replay   (sensor process)
  targets: 5                 # 5 | 4

eeg:
  board: cyton
  sample_rate: 250
  channels: [0, 1, 2, 3, 4, 5, 6, 7]
  channel_names: [O1, Oz, O2, POz, PO3, PO4, Pz, CPz]
  serial_port: auto

dsp:
  hop_s: 0.25
  notch_hz: 60.0
  notch_q: 30.0
  bandpass_high_hz: 48.0
  bandpass_order: 4
  # window_s and bandpass_low_hz come from the active stimulus profile

stimulus:
  profile: auto              # auto | hi | lo
  tile_layout: cross
  tile_px: 320
  contrast: 0.85
  cue_duration_s: 1.0
  label_font_px: 34
  integrity_drop_threshold: 5

  profiles:
    hi:
      min_refresh_hz: 120
      render: sinusoid
      frequencies: [8.0, 9.6, 11.4, 13.2, 15.0]
      phases:      [0.0, 1.5707963, 3.1415927, 4.7123890, 0.0]
      cancel_idx: 4
      window_s: 1.25
      bandpass_low_hz: 6.0
      fbcca_subband_low_hz: [6, 14, 22, 30, 38]
    lo:
      min_refresh_hz: 0
      render: divisor        # exact divisors of 60: 9, 8, 7, 5, 6
      frequencies: [6.667, 7.5, 8.571, 12.0, 10.0]
      phases:      [0.0, 1.5707963, 3.1415927, 4.7123890, 0.0]
      cancel_idx: 4          # 10.0 Hz: alpha-adjacent, lowest-cost false positive
      window_s: 2.0
      bandpass_low_hz: 5.0
      fbcca_subband_low_hz: [5, 12, 19, 26, 33]

classify:
  algorithm: auto            # auto | fbcca | etrca
  harmonics: 3
  fbcca:
    n_subbands: 5
    subband_high_hz: 48
    weight_a: 1.25
    weight_b: 0.25
  etrca:
    calibration_max_age_s: 7200
    model_dir: ./data/calibration

decision:
  rho_threshold: 0.35
  margin_ratio: 1.15
  dwell_windows: 3
  refractory_s: 1.0

calibration:
  blocks: 5
  trial_s: 3.0
  rest_s: 1.0

graph:
  db_path: ./data/kuzu
  embedding_dim: 384

retrieval:
  vector_top_k: 25
  hops: 2
  candidate_cap: 60
  select_k: 8

generation:
  n_intents: 4
  n_candidates: 3
  max_tokens: 2048
  timeout_s: 12.0

extraction:
  enabled: true
  confidence_threshold: 0.7
  max_new_nodes_per_turn: 4
  dedup_similarity: 0.88

reinforcement:
  edge_increment: 0.15
  node_increment: 0.10
  max_weight: 5.0

voice:
  cache_first: true
  cache_dir: ./data/audio_cache

telemetry:
  enabled: true
  queue_maxsize: 2000        # bounded; DROPS on overflow, never blocks
  flush_interval_ms: 500
  flush_batch: 500
  eeg_downsample: 1
  compress_after: 10m

spectator:
  enabled: true
  url: wss://<domain>/producer
  throttle_hz: 1.0
  send_raw_eeg: false        # NEVER true
  send_graph_content: false

privacy:
  local_mode: false
  show_costs: true
  price_table:
    gemini_in_per_1k: 0.000075
    gemini_out_per_1k: 0.0003
    elevenlabs_per_1k_chars: 0.30
    deepgram_per_minute: 0.0043

recording:
  enabled: true
  dir: ./data/sessions
```

`.env.example`:

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

OPENAI_COMPAT_BASE_URL=http://localhost:1234/v1
OPENAI_COMPAT_MODEL=
OPENAI_COMPAT_API_KEY=

DO_GRADIENT_BASE_URL=
DO_GRADIENT_MODEL=
DO_GRADIENT_API_KEY=

STT_PROVIDER=deepgram
DEEPGRAM_API_KEY=

TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
PIPER_MODEL_PATH=./models/en_US-lessac-medium.onnx

EMBEDDING_PROVIDER=minilm

TIMESCALE_DSN=

SPECTATOR_URL=
SPECTATOR_TOKEN=

EMOTIV_CLIENT_ID=
EMOTIV_CLIENT_SECRET=

DEMO_REPLAY=false
LOCAL_MODE=false
```

**Provider fallback chains** (`providers/registry.py`). Each link is skipped if its key is absent or its last call failed within 30 s:

- LLM: `gemini` → `openai_compat` → `do_gradient` → `static`
- STT: `deepgram` → `faster_whisper` → `manual`
- TTS: `cache` → `elevenlabs` → `piper` → `browser SpeechSynthesis`

**The last link in every chain never touches the network.** The backend therefore boots and serves a complete, correctly-shaped turn with no API keys at all.

**Local Mode** truncates every chain to its offline links, disables the spectator relay and routes telemetry to a local Postgres. Toggling requires no restart.

---

## 6. Contracts

All schemas live in `shared/schemas.py` as pydantic v2 models, mirrored by hand in `frontend/src/lib/types.ts`. Every message carries `type` and `ts` (float, UNIX seconds).

**These are frozen before any other work starts.** Everything in the system depends on them.

### 6.1 The selection contract

The single most important type in the system. Everything upstream of it is replaceable.

```python
class Selection(BaseModel):
    type: Literal["input.selection"]
    ts: float
    trial_id: str                    # must match the current trial or it is dropped
    target_idx: int                  # 0..n_targets-1
    confidence: float                # 0..1, adapter-defined
    source: str                      # "ssvep" | "keyboard" | "replay" | "emotiv"
    algorithm: str | None            # "fbcca" | "etrca" | None
```

### 6.2 ZMQ: P1 sensor → P3 backend (`bci.` prefix)

```python
class EegChunk(BaseModel):          # ~4 Hz
    type: Literal["bci.eeg"]
    ts: float
    fs: int
    channels: list[str]
    data: list[list[float]]          # [8][n], microvolts, post-filter
    railed: list[bool]

class PsdFrame(BaseModel):          # ~4 Hz
    type: Literal["bci.psd"]
    ts: float
    freqs: list[float]               # 0..48 Hz, 0.5 Hz bins
    power: list[float]               # occipital mean, dB
    peaks: list[float]               # power at each target frequency

class TargetScores(BaseModel):      # 4 Hz
    type: Literal["bci.scores"]
    ts: float
    algorithm: Literal["fbcca", "etrca"]
    rho: list[float]
    winner_idx: int
    margin: float
    above_threshold: bool
    dwell_count: int

class SensorStatus(BaseModel):      # 1 Hz
    type: Literal["bci.status"]
    ts: float
    source: Literal["cyton", "synthetic", "replay"]
    connected: bool
    configured: bool                 # has a stim.profile been received?
    samples_received: int
    dropped_samples: int
    railed_channels: list[int]
```

### 6.3 ZMQ: P3 → P2 stimulus (`stim.` prefix)

```python
class ShowTargets(BaseModel):
    type: Literal["stim.show_targets"]
    ts: float
    trial_id: str
    labels: list[str]
    round: Literal["intent", "candidate", "speller"]
    cue_idx: int | None              # calibration only

class StimControl(BaseModel):
    type: Literal["stim.control"]
    ts: float
    action: Literal["idle", "start_flicker", "stop_flicker", "message"]
    message: str | None
```

### 6.4 ZMQ: P2 → P3 (`stim.` prefix)

```python
class StimulusProfile(BaseModel):
    """Published once at startup after measuring the real refresh rate.
    P3 relays it to P1, which reconfigures before its first classification."""
    type: Literal["stim.profile"]
    ts: float
    profile: Literal["hi", "lo"]
    measured_refresh_hz: float
    frequencies: list[float]
    phases: list[float]
    cancel_idx: int
    window_s: float
    bandpass_low_hz: float
    fbcca_subband_low_hz: list[float]

class StimulusOnset(BaseModel):
    type: Literal["stim.onset"]
    ts: float                        # LSL-corrected
    trial_id: str
    frequencies: list[float]

class StimulusIntegrity(BaseModel):
    type: Literal["stim.integrity"]
    ts: float
    measured_refresh_hz: float
    dropped_frames_last_s: int
    frame_interval_std_ms: float
```

### 6.5 WebSocket: P3 → dashboard

Envelope `{"type": ..., "ts": ..., "payload": {...}}`.

| `type` | Rate | Payload |
|---|---|---|
| `eeg.trace` | 4 Hz | `{channels, data, fs}` |
| `eeg.psd` | 4 Hz | `{freqs, power, peaks}` |
| `bci.scores` | 4 Hz | mirrors `TargetScores` |
| `input.selection` | event | `{target_idx, label, round, confidence, source}` |
| `conv.transcript` | event | `{speaker, text, partner_id, partner_name, confidence}` |
| `conv.intents` | event | `{trial_id, labels}` |
| `conv.candidates` | event | `{trial_id, candidates, grounding}` |
| `conv.spoken` | event | `{text, voice, cached, latency_ms}` |
| `graph.snapshot` | on connect | `{nodes, edges}` |
| `graph.activate` | event | `{node_ids, edge_ids, reason}` |
| `graph.bloom` | event | `{nodes, edges}` |
| `fsm.state` | event | `{state, detail}` |
| `sys.status` | 1 Hz | `{input_source, input_badge, source, connected, replay, local_mode, profile, measured_refresh_hz, providers, stimulus_integrity, telemetry_dropped}` |
| `analytics.summary` | 2 s | `{accuracy_pct, mean_rho_by_target, selections_total, mean_selection_latency_s, itr_bits_per_min, drift}` |
| `privacy.flow` | event | `{stage, destination, bytes, description}` |
| `privacy.cost` | event | `{turn_id, items, turn_usd, session_usd}` |
| `spectator.link` | on connect | `{url, connected_viewers}` |

```python
class GraphNode(BaseModel):
    id: str
    label: str
    kind: Literal["Person","Place","Thing","Activity","Need","Memory"]
    weight: float
    last_accessed: float

class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    kind: str
    weight: float
```

### 6.6 REST

| Method | Path | Body | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | — | liveness + provider status |
| `GET` | `/api/graph` | — | full snapshot |
| `POST` | `/api/onboarding/seed` | `{bio, name}` | bio → seeded graph |
| `GET` | `/api/onboarding/status` | — | `{seeded, node_count}` |
| `POST` | `/api/partner` | `{partner_id}` | manual override |
| `POST` | `/api/utterance` | `{text}` | scripted-prompt advance |
| `POST` | `/api/mode` | `{mode}` | intent \| speller |
| `POST` | `/api/input` | `{adapter}` | hot-swap the input adapter |
| `POST` | `/api/calibration/start` | — | run an eTRCA block |
| `GET` | `/api/session/latest` | — | most recent recording |
| `GET` | `/api/analytics/summary` | — | continuous-aggregate rollup |
| `POST` | `/api/privacy/local_mode` | `{enabled}` | toggle, no restart |
| `GET` | `/api/privacy/flows` | — | what has left the machine |
| `POST` | `/api/privacy/purge` | `{scope}` | delete stored personal data |
| `GET` | `/api/spectator/link` | — | public URL + QR payload |

---

## 7. The input layer

**This is the abstraction that decouples every other subsystem from the EEG hardware.** Nothing downstream of `InputSource` knows or cares how a selection was produced.

### 7.1 Interface

`inputs/base.py`:

```python
class InputSource(ABC):
    name: str                        # "keyboard", "ssvep", ...
    badge: str | None                # UI badge text; None for the production path
    n_targets: int
    supports_labels: bool            # can the adapter display text on targets?

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def set_targets(self, trial_id: str, labels: list[str],
                          round: str) -> None:
        """Present n_targets options. For adapters that cannot render labels,
        the orchestrator is responsible for surfacing them elsewhere."""

    @abstractmethod
    def selections(self) -> AsyncIterator[Selection]:
        """Yields at most one Selection per trial_id."""

    def status(self) -> dict:
        """Adapter-specific health, merged into sys.status."""
        return {}
```

The orchestrator (§14) holds exactly one `InputSource`. Swapping adapters is a config change or a `POST /api/input`; no other code changes.

### 7.2 `keyboard` — the development adapter

**Build this first. It unblocks the entire team.**

Listens for number keys 1–5 in the dashboard and emits a `Selection` with `confidence: 1.0` and `source: "keyboard"`. Dashboard shows a persistent orange **`KEYBOARD INPUT`** badge (DEMO-3).

With this adapter, the full conversational pipeline — STT, retrieval, generation, TTS, graph writeback, every visualisation — is buildable and testable with no headset, no gel, no Cortex, and no signal processing in existence. Three of four people can work all weekend without touching hardware.

It is a development tool. It is never used in front of judges.

### 7.3 `ssvep` — the production adapter

Subscribes to `bci.selection` on ZMQ 5555, forwards as `Selection` with `source: "ssvep"`. Calls `set_targets` by publishing `stim.show_targets` on 5556. `badge` is `None`. This is the real path.

### 7.4 `replay` — the demo fallback

Drives the sensor process's `replay` source, so a recorded session flows through the **real classifier** and produces genuine selections. Badge: **`REPLAY — recorded HH:MM`**.

This is the honest crash-insurance (DEMO-1, DEMO-2). If the live demo fails, you say the room is electrically noisy and show a session recorded an hour ago. Every number a judge sees is real.

### 7.5 `emotiv` — optional secondary path

The EPOC X exposes band power (theta / alpha / betaL / betaH / gamma per sensor) and facial expressions through the free Cortex tier. Raw EEG is licence-gated and unavailable.

Two sub-modes, both gated on an offline feasibility test producing ≥80% accuracy at p<0.05:

- **`emotiv_bandpower`** — targets at 6 Hz (theta), 15 Hz (betaL), 20 Hz (betaH) on a separate stimulus surface; classification by nearest-centroid on the baseline-normalised 20-dimensional posterior band-power vector. Latency 3–4 s. Badge: **`EMOTIV BAND POWER`**.
- **`emotiv_wink`** — `winkL` / `winkR` from the Facial Expressions stream. Two targets, near-deterministic, ~10 minutes to build. **This is EOG/EMG, not EEG, and the UI badge and the pitch must both say so**: **`EMOTIV — MUSCLE (EOG/EMG)`**.

Neither is on the critical path. Neither is built before the OpenBCI path works. If the feasibility test fails, `emotiv_wink` remains available as a two-target input and the band-power mode is dropped.

**Do not drive the Speller with a two-target adapter.** Binary search over 28 symbols needs five decisions per character, and errors compound multiplicatively: at 95% per decision you get a clean five-letter word about a quarter of the time. Two-target adapters are for yes/no confirmation and scan-and-select, where one error costs one retry.

### 7.6 Badge rule

`sys.status.input_badge` is rendered by `StatusBar.tsx` in high contrast whenever non-null. The production `ssvep` adapter is the only one with a null badge. This is how DEMO-1 and DEMO-3 are enforced in code rather than in discipline.

---

## 8. Sensor process (P1)

### 8.1 Acquisition

`sources/cyton.py` uses BrainFlow with `BoardIds.CYTON_BOARD`. Serial port autodetection enumerates ports and picks the first matching `FTDI`/`usbserial`; `config.eeg.serial_port` overrides.

A dedicated thread calls `get_board_data()` every 100 ms and appends to a 5-second ring buffer. **That thread does nothing else** — no filtering, no classification, no I/O.

On `prepare_session()` failure, log and fall back to `synthetic` with a loud warning.

### 8.2 Filtering

Applied per extracted window, never to the ring buffer:

1. Per-channel mean removal
2. IIR notch at 60 Hz, `iirnotch(60, Q=30, fs=250)`, via `filtfilt`
3. 4th-order Butterworth bandpass from `profile.bandpass_low_hz` to 48.0 Hz, `sos` form, via `sosfiltfilt`
4. Common average reference across the 8 channels

Zero-phase filtering is mandatory: SSVEP classification depends on phase relationships and a causal filter's group delay smears them.

### 8.3 Classification

```python
class Classifier(ABC):
    @abstractmethod
    def score(self, window: np.ndarray) -> np.ndarray:
        """window: (n_channels, n_samples), filtered. Returns (n_targets,)."""
```

**FBCCA.** For each sub-band `m` in 0..4, bandpass between `profile.fbcca_subband_low_hz[m]` and 48 Hz. For each target `f_k`, build reference matrix `Y_k` of shape `(2*harmonics, n_samples)` containing `sin(2πhf_k t)`, `cos(2πhf_k t)` for `h` in 1..3. Compute the first canonical correlation `ρ_{m,k}` using a direct SVD implementation, not `sklearn.CCA` — this runs 100 CCAs per second and the direct form is roughly 20× faster.

Combine: `ρ_k = Σ_m w(m) · ρ²_{m,k}` where `w(m) = (m+1)^(-1.25) + 0.25`.

`fbcca.py` holds no frequency constants. Everything comes from `stim.profile`.

**eTRCA.** Per target, compute the spatial filter maximising inter-trial over intra-trial covariance; the ensemble filter concatenates all per-target filters. At test time, correlate the spatially-filtered window against each target's trial-averaged template, combined with an FBCCA term at 0.3 weight. Persisted to `data/calibration/{pilot}_{ts}.npz`.

**Selection.** With `algorithm: auto`, use eTRCA if a calibration file exists for the active pilot under `calibration_max_age_s`; otherwise FBCCA. Log the choice; do not surface it in the UI.

### 8.4 Synthetic source

Must produce signals a real classifier genuinely has to solve. At 250 Hz across 8 channels:

- **Pink noise** at 15 µV RMS
- **Alpha bump** at 10 Hz, 8 µV, amplitude-modulated by a slow random walk. The `hi` profile excludes 10.0 Hz for this reason; the `lo` profile parks it on the Cancel tile.
- **SSVEP**: when an attended target is set, inject `A · Σ_h (1/h) · sin(2πh f t + φ_h)` with `A` ramping to 3 µV over 400 ms. O1/Oz/O2/POz get full amplitude, PO3/PO4 get 0.7×, Pz/CPz get 0.4×.
- **60 Hz line noise** at 20 µV, so the notch filter is exercised
- **Blink artifacts** on a Poisson schedule (~1 per 8 s): 300 ms, 80 µV, weighted frontally

Exposes `set_attended_target(idx | None)`.

`tests/test_fbcca.py` asserts ≥95% accuracy over 200 synthetic windows at 3 µV, and ≤2% false positives with no attended target.

### 8.5 Decision state machine

```
IDLE ──(above_threshold and margin_ok)──► DWELL(winner, 1)
DWELL(w,n) ──(same winner, still ok)──► DWELL(w, n+1)
DWELL(w,n) ──(different winner or below threshold)──► IDLE
DWELL(w, dwell_windows) ──► emit Selection ──► REFRACTORY
REFRACTORY ──(refractory_s elapsed)──► IDLE
```

`above_threshold` is `rho[winner] >= rho_threshold`. `margin_ok` is `rho[winner]/rho[second] >= margin_ratio`. **Both are required.** The threshold alone is insufficient — noise pushes several correlations up together, and the margin test is what makes the idle state credible when a judge looks at the screen.

### 8.6 Recorder

Always on. Writes `data/sessions/{ISO8601}.npz` with the raw unfiltered buffer, timestamps, all received onset markers, and a JSON sidecar of the config in force. Directly loadable by `sources/replay.py`; this is what makes DEMO-2 possible.

---

## 9. Stimulus process (P2)

### 9.1 Rendering

PsychoPy `visual.Window(fullscr=True, waitBlanking=True, useFBO=True, winType='pyglet')`. Vsync-locked; one `win.flip()` per loop iteration.

Luminance is always a **sinusoid sampled at frame boundaries**:

```
L_k(n) = 0.5 * (1 + contrast * sin(2π f_k n / refresh_hz + φ_k))
```

Square-wave flicker spreads energy across harmonics and makes adjacent frequencies harder to separate. Sinusoidal keeps the spectrum concentrated at the fundamental, which is what CCA looks for.

### 9.2 Refresh profiles

`profile.py` runs before the first trial:

1. Render 300 blank frames, discarding the first 60
2. `measured_refresh_hz = 1 / median_frame_interval`
3. Select `hi` if `>= 120`, else `lo`
4. Publish `stim.profile`

**Do not trust what the OS reports.** Measure it. A panel set to 165 Hz actually delivering 60 because of a dock or power profile is a failure that looks exactly like a broken classifier.

| | `hi` | `lo` |
|---|---|---|
| Trigger | measured ≥ 120 Hz | < 120 Hz |
| Frequencies | 8.0, 9.6, 11.4, 13.2, 15.0 | 6.667, 7.5, 8.571, 12.0, 10.0 |
| Divisors of 60? | no | yes: 60/9, 60/8, 60/7, 60/5, 60/6 |
| Cancel tile | 15.0 Hz | **10.0 Hz** |
| Window | 1.25 s | 2.0 s |
| Bandpass floor | 6.0 Hz | 5.0 Hz |
| Min target spacing | 1.4 Hz | 0.83 Hz |

Three notes on `lo`:

**Exact divisors.** At 60 Hz there are only about nine usable divisor frequencies in the SSVEP band, so the set is forced. Rendering on exact divisors gives zero quantisation error, which partly offsets everything else being worse.

**Wider window.** `lo` frequencies sit as close as 0.83 Hz apart. A 1.25 s window resolves 0.80 Hz — no margin. At 2.0 s the resolution is 0.50 Hz. The cost is ~2.75 s per selection instead of 2.0 s. That is the honest price of a 60 Hz panel.

**10.0 Hz on Cancel, deliberately.** Resting alpha peaks near 10 Hz and will occasionally false-trigger a 10 Hz target. The divisor grid gives no way to avoid that region while fitting five targets, so it goes on the tile whose false positive is harmless — Cancel just returns to idle.

**Harmonic collision rule.** For every pair of targets, no 2× or 3× harmonic of one may land within 0.5 Hz of another's fundamental. Both shipped sets satisfy this. Changing one frequency without re-checking the whole matrix silently degrades two targets at once and looks like a hardware fault. `tests/test_profiles.py` enforces it.

### 9.3 Tile layout

```
            ┌───────────┐
            │  TILE 0   │   f[0]
            └───────────┘
 ┌──────────┐           ┌──────────┐
 │ TILE 2   │           │ TILE 1   │   f[2] / f[1]
 └──────────┘           └──────────┘
            ┌───────────┐
            │  TILE 3   │   f[3]
            └───────────┘
            ┌───────────┐
            │  CANCEL   │   f[cancel_idx]
            └───────────┘
```

Each tile is `tile_px` square with its label rendered at **constant luminance** — the text does not flicker. Flickering text is unreadable and destroys the paradigm. Minimum 120 px between tiles to limit spatial crosstalk.

Tile index → frequency mapping comes from the active profile. Nothing downstream of `profile.py` hardcodes a frequency.

### 9.4 Trial sequence

1. Receive `stim.show_targets`; render labels on static tiles
2. `cue_duration_s` with no flicker, so the pilot can read and decide
3. Begin flicker; publish `stim.onset` and push an LSL marker in the same frame
4. Continue until `stop_flicker`
5. Briefly highlight the selected tile (400 ms solid), return to idle

### 9.5 Integrity monitoring

`integrity.py` records every flip interval and publishes `stim.integrity` once per second: measured refresh, count of intervals exceeding 1.5× nominal, and interval standard deviation. Over `integrity_drop_threshold` drops in one second logs at ERROR.

Frame drops are the number one silent killer of SSVEP accuracy. Without this metric you will debug the classifier when the problem is the renderer.

`scripts/check_stimulus.py` runs the loop standalone for 30 s and prints a pass/fail verdict. **Run it on every machine that will show the stimulus, at hour 0.** If a machine cannot hold its nominal rate with near-zero drops, it is a development machine only — which is fine, because the synthetic source generates SSVEP independently of any display.

### 9.6 LSL

`markers.py` creates `StreamOutlet(StreamInfo("Flick-Markers", "Markers", 1, 0, "string", uid))`. Each onset pushes `f"onset:{trial_id}:{cue_idx}"`.

No extra hardware; `pylsl` bundles `liblsl` and runs over loopback. It exists because eTRCA training needs sample-accurate alignment between stimulus onset and the EEG timeline, and hand-rolling that across two Python processes will be off by tens of milliseconds in ways that silently degrade the spatial filters.

---

## 10. Graph service

### 10.1 Schema

Requires `kuzu >= 0.7`. Executed by `graph.py::ensure_schema()` on first run.

```sql
CREATE NODE TABLE Person(
  id STRING, name STRING, relationship STRING,
  address_terms STRING[], notes STRING,
  embedding DOUBLE[384], weight DOUBLE,
  created_at TIMESTAMP, last_accessed TIMESTAMP,
  PRIMARY KEY (id));

CREATE NODE TABLE Place(
  id STRING, name STRING, notes STRING,
  embedding DOUBLE[384], weight DOUBLE,
  created_at TIMESTAMP, last_accessed TIMESTAMP, PRIMARY KEY (id));

CREATE NODE TABLE Thing(
  id STRING, name STRING, category STRING, notes STRING,
  embedding DOUBLE[384], weight DOUBLE,
  created_at TIMESTAMP, last_accessed TIMESTAMP, PRIMARY KEY (id));

CREATE NODE TABLE Activity(
  id STRING, name STRING, time_of_day STRING, notes STRING,
  embedding DOUBLE[384], weight DOUBLE,
  created_at TIMESTAMP, last_accessed TIMESTAMP, PRIMARY KEY (id));

CREATE NODE TABLE Need(
  id STRING, name STRING, urgency STRING, notes STRING,
  embedding DOUBLE[384], weight DOUBLE,
  created_at TIMESTAMP, last_accessed TIMESTAMP, PRIMARY KEY (id));

CREATE NODE TABLE Memory(
  id STRING, text STRING, occurred_on STRING, source STRING,
  embedding DOUBLE[384], weight DOUBLE,
  created_at TIMESTAMP, last_accessed TIMESTAMP, PRIMARY KEY (id));

CREATE REL TABLE KNOWS(FROM Person TO Person,
  weight DOUBLE, count INT64, last_reinforced TIMESTAMP);

CREATE REL TABLE LIKES(
  FROM Person TO Thing, FROM Person TO Activity,
  FROM Person TO Place, FROM Person TO Person,
  weight DOUBLE, count INT64, strength DOUBLE, last_reinforced TIMESTAMP);

CREATE REL TABLE DISLIKES(
  FROM Person TO Thing, FROM Person TO Activity, FROM Person TO Place,
  weight DOUBLE, count INT64, strength DOUBLE, last_reinforced TIMESTAMP);

CREATE REL TABLE NEEDS(
  FROM Person TO Need, FROM Person TO Thing,
  weight DOUBLE, count INT64, last_reinforced TIMESTAMP);

CREATE REL TABLE LOCATED_AT(
  FROM Thing TO Place, FROM Activity TO Place, FROM Person TO Place,
  weight DOUBLE, count INT64, last_reinforced TIMESTAMP);

CREATE REL TABLE DOES(FROM Person TO Activity,
  weight DOUBLE, count INT64, last_reinforced TIMESTAMP);

CREATE REL TABLE INVOLVES(
  FROM Memory TO Person, FROM Memory TO Place,
  FROM Memory TO Thing, FROM Memory TO Activity,
  weight DOUBLE, count INT64, last_reinforced TIMESTAMP);

CREATE REL TABLE RELATES_TO(
  FROM Thing TO Thing, FROM Activity TO Activity,
  FROM Thing TO Activity, FROM Need TO Thing,
  weight DOUBLE, count INT64, last_reinforced TIMESTAMP);
```

`LIKES` and `DISLIKES` are separate relation types rather than one signed edge: the LLM emits these far more reliably than a numeric valence, and `strength` (0..1) carries intensity where it matters.

The user is a `Person` with `id = "user"` and `relationship = "self"`. Everything hangs off that.

### 10.2 Operations

```python
class GraphService:
    def ensure_schema(self) -> None
    def seed_from_json(self, payload: dict) -> SeedResult
    def snapshot(self) -> tuple[list[GraphNode], list[GraphEdge]]
    def vector_search(self, q: np.ndarray, k: int) -> list[NodeRef]
    def expand(self, seeds: list[NodeRef], hops: int, cap: int) -> list[NodeRef]
    def reinforce(self, node_ids: list[str], edge_ids: list[str]) -> None
    def upsert_node(self, kind: str, props: dict) -> str
    def upsert_edge(self, kind: str, src: str, dst: str, props: dict) -> str
    def people(self) -> list[Person]
    def node_count(self) -> int
```

`vector_search` reads all `(id, kind, embedding)` into a cached numpy matrix on first call, invalidated on any write. At 150–300 nodes this is a sub-millisecond dot product; a vector index would be pure overhead.

`expand` is breadth-first Cypher:

```cypher
MATCH (s)-[r*1..2]-(n)
WHERE s.id IN $seed_ids
RETURN DISTINCT n, r
ORDER BY n.weight DESC
LIMIT $cap
```

---

## 11. Retrieval

Four stages, under 150 ms total.

1. **Seed.** Embed the query (partner utterance for round one; utterance + chosen intent for round two). Cosine against all node embeddings. Top `vector_top_k` (25).
2. **Expand.** Two-hop traversal from seeds, union with seeds, truncate to `candidate_cap` (60) preferring higher weight.
3. **Partner boost.** If a partner is identified, unconditionally add that `Person` node and everything within one hop. **This is what makes the same intent produce a different sentence depending on who is listening**, and it is the most persuasive behaviour in the demo.
4. **Submodular selection.** `apricot.FacilityLocationSelection(n_samples=select_k, metric='cosine')` over the candidate embeddings.

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

All calls go through `LLMProvider.complete(system, user, json_mode=...)` with the configured generation token allowance and timeout. The generation stage has a 12 s deadline, including one retry on malformed JSON using a repair prompt. The 2048-token allowance leaves room for thinking and the complete JSON response; Gemini 3 uses low thinking and Gemini 2.5 Flash disables thinking. A second failure or the stage deadline falls to the offline placeholder.

### 12.1 Intent labels

```
You write short intent labels for a speech device used by someone who cannot speak.

They will choose ONE label by looking at it. The label is not the sentence they
will say — it is the DIRECTION their reply will take.

Rules:
- Exactly 4 labels.
- Each label is 1 to 3 words. Never more.
- Labels must be clearly distinct in meaning from one another.
- Cover a genuine range: at minimum one affirmative, one negative or deflecting,
  and one that asks something back.
- Use the person's own world where it helps (names, places, routines from CONTEXT).
- Never include punctuation. Never number them.

Return strict JSON, nothing else:
{"labels": ["...", "...", "...", "..."]}

CONTEXT ABOUT THE PERSON:
{context}

WHO IS SPEAKING TO THEM: {partner_name} ({partner_relationship})
WHAT THEY JUST SAID: "{utterance}"
```

Rendered on tiles 0–3. Tile 4 is always "Cancel", never LLM-generated.

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

## 13. Orchestrator

`backend/app/orchestrator.py`. One instance, one asyncio task. Every transition broadcasts `fsm.state`.

```
              ┌──────────────┐
              │  UNSEEDED    │  dashboard shows onboarding
              └──────┬───────┘
                     │ POST /api/onboarding/seed
              ┌──────▼───────┐
        ┌────►│    IDLE      │  tiles dark, mic armed
        │     └──────┬───────┘
        │            │ VAD speech-end  OR  POST /api/utterance
        │     ┌──────▼───────┐
        │     │ TRANSCRIBING │
        │     ├──────▼───────┤
        │     │  GROUNDING   │  partner id + retrieval → graph.activate
        │     ├──────▼───────┤
        │     │ INTENT_GEN   │  LLM → 4 labels
        │     ├──────▼───────┤
        │     │ INTENT_WAIT  │  awaiting Selection
        │     └──┬────────┬──┘
        │        │        │ Cancel ──────────────► IDLE
        │     ┌──▼───────────┐
        │     │CANDIDATE_GEN │  retrieval round 2 → 3 sentences
        │     ├──────▼───────┤
        │     │CANDIDATE_WAIT│
        │     └──┬────────┬──┘
        │        │        │ Cancel ──► INTENT_WAIT (same labels)
        │     ┌──▼───────────┐
        │     │  SPEAKING    │  cache → ElevenLabs → Piper → browser
        │     ├──────▼───────┤
        │     │  LEARNING    │  reinforce + extract + bloom
        └─────┴──────────────┘
```

**Timeouts.** `INTENT_WAIT` and `CANDIDATE_WAIT` expire after 30 s and return to `IDLE` with a "No selection — listening again" message. Generation states expire at `generation.timeout_s` and fall through their provider chains.

**Speller mode** replaces `INTENT_GEN`/`INTENT_WAIT` with a loop over `speller.py`'s N-ary tree (N configurable, default 4), appending one character per traversal, exiting to `SPEAKING` on the SPEAK leaf.

**Concurrency rule.** The orchestrator drops any `Selection` arriving outside a `*_WAIT` state, and stamps every `show_targets` with a fresh `trial_id`. A selection whose `trial_id` does not match the current one is discarded. Without this you get stale-suggestion races.

---

## 14. Onboarding

Served at `/` when `GET /api/onboarding/status` reports `seeded: false`.

`BioWizard.tsx` shows one large textarea pre-filled with the fixture persona, so a full seed is one click on stage. The operator can edit or replace it entirely.

`POST /api/onboarding/seed`:

1. LLM call → JSON graph of nodes and edges. First pass asks for 40–60 nodes across a balanced spread of kinds; a second expansion call enriches each Person and Activity with related Things, Places and Memories. Target 150–300 nodes.
2. Validate against the pydantic seed schema; drop malformed entries rather than failing
3. Embed every node's display text
4. Insert into Kuzu in one transaction
5. **Stream `graph.bloom` in batches of ~10 nodes at 150 ms intervals**, so the dashboard shows the brain *growing* rather than appearing

That streaming detail is worth the twenty minutes. A graph that materialises instantly looks like a fixture; a graph that grows looks like the system learning, and it is the same data either way.

Fixture persona (`data/fixtures/persona_marcus.json`):

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

### 16.1 Layout

```
┌────────────────────────────────────────────────────────────────────┐
│ StatusBar: ● LIVE  165.0 Hz / 0 drops  LLM ● STT ● TTS ●  [BADGE]  │
├──────────────────────────────┬─────────────────────────────────────┤
│                              │  Transcript                          │
│   MemoryBrain (3D)           ├─────────────────────────────────────┤
│   3d-force-graph             │  TargetScores                        │
│   ~60% of viewport           │  ▓▓▓▓░░ 8.0   ρ=0.21                │
│                              │  ▓▓▓▓▓▓▓▓ 9.6  ρ=0.58  ◄ dwell 2/3  │
│   pulse on retrieval         │  ▓▓░░░░ 11.4  ρ=0.14                │
│   glow when selected         ├─────────────────────────────────────┤
│   bloom when learned         │  PsdPlot                             │
├──────────────────────────────┴─────────────────────────────────────┤
│  EegTrace — 8 channels, 4 s scrolling                               │
├────────────────────────────────────────────────────────────────────┤
│  CandidatePanel — 3 sentences, chosen one enlarges and speaks        │
├──────────────────────┬──────────────────────┬──────────────────────┤
│ SessionAnalytics     │ PrivacyPanel         │ SpectatorQR          │
└──────────────────────┴──────────────────────┴──────────────────────┘
```

The bottom row collapses to a tabbed strip on narrow viewports. Those three panels are independently removable; nothing else references them.

### 16.2 Component rules

**`MemoryBrain.tsx`** wraps `3d-force-graph` imperatively via a ref, outside React's render cycle. React state changes must never re-instantiate the graph; use the library's `graphData()` mutation API. Node size maps to weight, colour to kind. Three animations:

- *pulse* — `graph.activate`, travelling highlight along traversed edges, 600 ms
- *glow* — grounding nodes, sustained emissive 3 s then decay
- *bloom* — `graph.bloom`, node scales 0→full over 500 ms with edges drawing in

**`EegTrace.tsx`** / **`PsdPlot.tsx`** use **uPlot**, mounted via ref, updated with `setData()`. Not Plotly, not Chart.js — at 8 channels × 250 Hz with 4 Hz redraws they drop to single-digit FPS and the panel looks broken, which is worse than not having it.

**`TargetScores.tsx`** shows five bars with the threshold as a vertical line and dwell as filled pips. **This is the panel that proves the idle state is real** — judges watch the bars sit below the line while the pilot looks away.

**`StatusBar.tsx`** renders provider health, stimulus integrity, and `sys.status.input_badge` in high contrast whenever non-null (§7.6).

### 16.3 WebSocket client

Single connection, exponential-backoff reconnect (250 ms → 4 s cap), typed discriminated union on `type`. On reconnect, request a fresh `graph.snapshot`.

**High-rate streams bypass React state entirely.** `eeg.trace`, `eeg.psd` and `bci.scores` write into refs consumed by the plot components' animation frames. Putting 4 Hz × 3 streams through `useState` causes visible jank in the 3D graph.

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

`registry.py` builds a `FallbackChain` per slot from env vars. Every provider is lazily constructed on first use and wrapped in a circuit breaker: three consecutive failures marks it unhealthy for 30 s and the chain skips it. Health is reported in `sys.status`.

The last link in every chain is local, offline and never fails. That is what makes SW-13 real: the backend boots and serves a complete turn with no API keys, so frontend and graph work proceed while credentials are being sorted out.

---

## 18. Telemetry — TimescaleDB

### 18.1 Schema

`migrations/001_timescale.sql`:

```sql
-- Wide format: 250 rows/s, not 2000. Narrow is 8x the row overhead for no
-- analytical benefit, since we always read all channels together.
CREATE TABLE eeg_frames (
  ts TIMESTAMPTZ NOT NULL, session_id TEXT NOT NULL,
  ch0 REAL, ch1 REAL, ch2 REAL, ch3 REAL,
  ch4 REAL, ch5 REAL, ch6 REAL, ch7 REAL);
SELECT create_hypertable('eeg_frames','ts',chunk_time_interval=>INTERVAL '1 minute');

CREATE TABLE bci_scores (
  ts TIMESTAMPTZ NOT NULL, session_id TEXT NOT NULL,
  algorithm TEXT NOT NULL, target_idx SMALLINT NOT NULL,
  frequency REAL NOT NULL, rho REAL NOT NULL,
  is_winner BOOLEAN NOT NULL, margin REAL, dwell_count SMALLINT);
SELECT create_hypertable('bci_scores','ts',chunk_time_interval=>INTERVAL '5 minutes');

CREATE TABLE selections (
  ts TIMESTAMPTZ NOT NULL, session_id TEXT NOT NULL, trial_id TEXT NOT NULL,
  round TEXT NOT NULL, target_idx SMALLINT NOT NULL, label TEXT,
  confidence REAL, source TEXT, cued_idx SMALLINT, latency_s REAL);
SELECT create_hypertable('selections','ts',chunk_time_interval=>INTERVAL '1 hour');

CREATE TABLE stimulus_integrity (
  ts TIMESTAMPTZ NOT NULL, session_id TEXT NOT NULL, profile TEXT NOT NULL,
  measured_refresh_hz REAL NOT NULL, dropped_frames SMALLINT NOT NULL,
  interval_std_ms REAL);
SELECT create_hypertable('stimulus_integrity','ts',chunk_time_interval=>INTERVAL '1 hour');

CREATE TABLE turns (
  ts TIMESTAMPTZ NOT NULL, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
  partner_id TEXT, utterance TEXT, intent TEXT, spoken_text TEXT,
  llm_provider TEXT, tts_tier TEXT, total_latency_ms INTEGER,
  turn_usd NUMERIC(10,6));
SELECT create_hypertable('turns','ts',chunk_time_interval=>INTERVAL '1 hour');

CREATE MATERIALIZED VIEW rho_1s WITH (timescaledb.continuous) AS
SELECT time_bucket('1 second', ts) AS bucket, session_id, target_idx,
       avg(rho) AS mean_rho, max(rho) AS max_rho
FROM bci_scores GROUP BY bucket, session_id, target_idx;

CREATE MATERIALIZED VIEW accuracy_1m WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', ts) AS bucket, session_id,
       count(*) AS n,
       count(*) FILTER (WHERE cued_idx = target_idx) AS n_correct,
       avg(latency_s) AS mean_latency_s
FROM selections WHERE cued_idx IS NOT NULL GROUP BY bucket, session_id;

SELECT add_continuous_aggregate_policy('rho_1s',
  start_offset => INTERVAL '10 minutes',
  end_offset => INTERVAL '1 second',
  schedule_interval => INTERVAL '2 seconds');

ALTER TABLE eeg_frames SET (timescaledb.compress,
  timescaledb.compress_segmentby = 'session_id');
SELECT add_compression_policy('eeg_frames', INTERVAL '10 minutes');
```

### 18.2 The rule that matters

**The database must never be able to stall the pipeline.**

`telemetry.py` exposes a synchronous `emit(record)` that does exactly one thing: `queue.put_nowait`. On `QueueFull` it increments a dropped counter and returns. It never awaits, never retries, never raises.

A consumer task drains every `flush_interval_ms`, batches up to `flush_batch` rows per table, and writes via `asyncpg.copy_records_to_table`. If the database is unreachable, the consumer logs once per 30 s and keeps draining into the void so the queue never backs up.

`tests/test_telemetry.py` asserts that with the consumer stalled, 10,000 `emit()` calls complete in under 50 ms and the dropped counter equals the overflow.

Dropped count surfaces in `sys.status`. If non-zero, raise `eeg_downsample` to 2 — losing half the stored EEG resolution is acceptable; losing a classification is not.

### 18.3 Analytics panel

`SessionAnalytics.tsx`, fed by `analytics.summary` every 2 s:

- **Accuracy over time**, from `accuracy_1m`
- **Mean correlation per target**, from `rho_1s`, five sparklines. Reveals a bad electrode instantly — one target's ρ sits flat while the others move.
- **Selection latency distribution**
- **Information Transfer Rate** in bits/min, from accuracy, target count and mean selection time. This is the standard BCI performance metric and it is what lets you compare a semantic interface against a character speller with a real measurement behind it.
- **Frame integrity strip**, overlaid with selection events

This panel is also the honest answer to "how do you know it's working?" It is a measurement, not a claim.

---

## 19. Spectator relay

A judge three metres away cannot read the dashboard. A QR code on the pilot's table opens a phone-sized live view: which target is winning, the transcript, the sentence just spoken, a memory-node counter.

```
Machine A ──outbound WS──► DO droplet ──WS──► judge phones
          (producer)        relay.py         static/index.html
```

**Outbound only.** Machine A dials the relay; the relay never dials in, never sends commands, and nothing arriving from it enters the pipeline. `spectator.py` is a write-only client. This is a hard constraint: a publicly reachable endpoint that can influence a live BCI is not something to build at 4 a.m.

$6/mo basic droplet, Docker, Caddy for TLS, domain from GoDaddy Registry.

**What crosses the wire:**

| Sent | Not sent |
|---|---|
| Winning target index + label, 1 Hz | Raw EEG, ever |
| Correlation values, downsampled to 1 Hz | Per-window score streams |
| Partner utterance transcript | Personal graph node text |
| Spoken sentences | Node/edge contents, embeddings |
| Node and edge **counts** by kind | The persona's private details |
| Profile, refresh, dropped frames | Keys, internal identifiers |

The spoken sentences are already public — they are being said aloud in a room full of people. The graph contents are not, and they do not leave the machine.

**Gradient AI** serves an OpenAI-compatible endpoint, so it slots into `llm_openai_compat.py` with no new code — only three env vars. It sits third in the chain, giving the LLM path a second network vendor if Gemini rate-limits during judging.

---

## 20. Data and privacy

This system builds a structured model of a disabled person's family, home, medical needs and daily routine, then sends fragments to three cloud vendors on every turn. That is the correct trade for capability, and it is exactly the situation where a user deserves to see what is happening and be able to stop it.

**Data flow ledger.** Every outbound call emits `privacy.flow`. The panel renders:

```
This session, data has left this machine 14 times:

  → Gemini (Google)     9 calls   intent labels, sentences, fact extraction
                                  sends: partner utterance + 8 retrieved facts
  → ElevenLabs          4 calls   speech synthesis
                                  sends: the sentence text only
  → Deepgram            1 call    transcription
                                  sends: 3.2 s of microphone audio
  → Spectator relay   312 events  public live view
                                  sends: selections + spoken lines. No graph content.

Never sent anywhere: your memory graph, raw EEG, voice enrollment audio
Stored only here:    Kuzu graph (247 nodes), EEG telemetry (local Postgres)
```

The instrumentation is one decorator on each provider method. Roughly 40 lines.

**Cost visibility.** `cost.py` accumulates tokens, characters and audio seconds per turn, multiplies by `privacy.price_table`, emits `privacy.cost`. This is honest about something most AI demos hide: a system a disabled person depends on for speech has a running per-sentence cost, and if that is $0.004 per sentence then a day of conversation is a real number a family would want to know.

**Local Mode.** One toggle. LLM truncates to a local endpoint then static; STT to `faster_whisper`; TTS to cache then Piper (no voice clone — **say this plainly in the UI, do not hide the downgrade**); spectator disconnects; telemetry goes local. A `LOCAL MODE` badge appears. No restart.

**This is the demo moment.** Mid-pitch, flip the toggle, disconnect the network, complete another full turn — slower, generic voice, working. "This keeps working when the internet doesn't" is worth nothing asserted and a great deal demonstrated.

**Purge.** `POST /api/privacy/purge` with scope `graph` drops and recreates the Kuzu database; `telemetry` deletes the session's rows; `all` does both plus clears the audio cache. Confirmation required. Twenty minutes of work, and the difference between a privacy panel that informs and one that gives control.

---

## 21. Build plan

### 21.1 Roles

| | Owner | Scope |
|---|---|---|
| **Dev A** | | Orchestrator FSM, FastAPI, WS hub, provider layer, input layer, config, integration. **Also the pilot — so Dev A does not present.** |
| **Dev B** | | Sensor process end to end, and the stimulus process. Both halves of one closed loop; splitting them across people creates a synchronisation bug nobody owns. |
| **Dev C** | | Entire frontend. |
| **Dev D** | | Graph, retrieval, generation, extraction, partner ID, onboarding, prompts, persona, speller. **Presents.** |

### 21.2 Schedule

| Hours | Dev A | Dev B | Dev C | Dev D |
|---|---|---|---|---|
| **0–2** | Repo, `uv`, config, **`shared/schemas.py`**, `bus.py`, `run.sh`, GoDaddy domain. **Publish schemas by hour 2 — everyone is blocked until this lands.** | `check_stimulus.py` on both machines; record measured refresh and profile for each. Then gel the cap and confirm the Cyton streams. | Vite + React + TS + Tailwind scaffold, WS client against a mock, layout shells | Kuzu install, DDL, `ensure_schema()`, hand-written 20-node graph |
| **2–5** | **`inputs/base.py` + `inputs/keyboard.py`.** This unblocks C and D for the rest of the build. | `sources/synthetic.py` — **priority, unblocks everyone** | MemoryBrain with static data, EegTrace + PsdPlot on synthetic | `graph.py` CRUD + vector search, embeddings, retrieval stages 1–2 |
| **5–12** | FastAPI skeleton, WS hub, provider ABCs + offline fallbacks, orchestrator FSM on stubs | `profile.py`, both render modes, stimulus renderer, integrity, LSL | TargetScores, Transcript, CandidatePanel, StatusBar, wired to real WS | retrieval stages 3–4, `generation.py` + prompts against Gemini |
| **12–13** | **CROSS-MACHINE REHEARSAL.** Clean clone onto Machine A, `uv sync`, all four processes, confirm the `hi` profile and stable stimulus. Fix every portability break now. | | | |
| **13–18** | Gemini + ElevenLabs providers, `voice.py` chain + cache, `cost.py` decorator | `dsp.py`, `fbcca.py`, `decision.py`; `test_fbcca` and `test_profiles` passing ≥95% | Onboarding wizard, bloom/pulse/glow | `extraction.py`, `partner.py`, dedup |
| **18–22** | **CHECKPOINT 1.** All four processes, synthetic source, full turn on Machine A. Sleep rotation: two down, two up. | | | |
| **22–26** | `telemetry.py` + migration + Tiger Cloud | Cyton live: first real classification | `SessionAnalytics.tsx` | `onboarding.py`, persona fixture, streamed bloom |
| **26–29** | **CHECKPOINT 2.** Real EEG, real LLM, real voice, real telemetry, full turn end to end. | | | |
| **29–32** | Deploy `spectator/`, wire it, point the domain | eTRCA + calibration **only if checkpoint 2 was clean** | `SpectatorQR.tsx`, `PrivacyPanel.tsx`, Local Mode | Speller (~2 h), pitch script, Devpost draft |
| **32–34** | **FEATURE FREEZE.** `prerender_cache.py`. Backup video. Clean replay session. Verify Local Mode with the network physically off. | | | |
| **34–36** | Devpost writeup with a distinct paragraph per track, README, `CREDITS.md`, rehearse three times with the cap on. | | | |

### 21.3 Critical path

`shared/schemas.py` (h2) → `inputs/keyboard.py` (h5) → `sources/synthetic.py` (h5) → orchestrator on stubs (h12) → checkpoint 1 (h22).

Everything else can slip. **The keyboard adapter and the synthetic source are what let three people build a complete system while the fourth is still gelling electrodes.**

### 21.4 Cut order

1. eTRCA
2. Privacy panel and Local Mode (forfeits Assurant)
3. Speller
4. Spectator relay (forfeits DigitalOcean; keep the Gradient provider, it is three env vars)
5. Session Analytics panel (keep the telemetry *sink* — that is the substantive Tiger Data use)
6. Fact extraction writeback (keep edge reinforcement)
7. Partner identification (hardcode one partner)
8. Onboarding wizard (load the fixture)

**Never cut:** the idle state, the PSD plot, the memory brain, the voice clone. Those four are the demo.

Cuts 2, 4 and 5 forfeit a sponsor track and cost the core demo nothing. Cuts 6–8 keep tracks but weaken the demo. **At hour 30, cut tracks, not the demo.**

---

## 22. Failure modes

| Failure | Detection | Response |
|---|---|---|
| Cyton dongle absent | Exception at startup | Fall back to synthetic, badge shown, log loudly |
| Cyton powered over USB | Massive 60 Hz band on every channel | Batteries only. This is the single most common hardware mistake. |
| Electrode railed | `railed` in `SensorStatus` | Dashboard marks it red; classifier excludes it from CCA |
| Frame drops > threshold | `stim.integrity` | Log ERROR; sustained > 10 s shows a dashboard warning |
| Panel silently at 60 Hz | `profile.py` selects `lo` unexpectedly | Check dock, VRR, power profile. **Do not override the profile** — `lo` is correct for whatever the panel is actually doing. |
| P1 classifies before configuration | Assertion | P1 refuses until `stim.profile` arrives. If this fires, the ZMQ SUB is misconfigured. |
| Frequency changed without checking harmonics | Exactly two targets degrade together | Run `test_profiles.py` |
| Classification never fires | `dwell_count` never reaches 3 | Lower `rho_threshold` to 0.28; check the pilot is fixating tile centres |
| Alpha false-triggers | Selections fire with eyes closed | Confirm no target at 10.0 Hz on `hi`; raise `margin_ratio` to 1.25 |
| Telemetry queue saturating | Non-zero drop counter | Raise `eeg_downsample`. **Never raise `queue_maxsize`** — that trades a dropped row for a stalled pipeline. |
| TimescaleDB unreachable | Consumer logs once per 30 s | Nothing else changes; telemetry is best-effort by design |
| LLM timeout | `generation.timeout_s` elapsed | Use the offline placeholder at the stage deadline. The turn always completes. |
| STT garbage | Confidence < 0.5 or < 2 words | Discard; stay IDLE. Operator can use `POST /api/utterance`. |
| ElevenLabs down | HTTP error | Cache → Piper → browser. Never silent. |
| Network dies entirely | Provider dots red | Cached audio + static LLM keep a scripted demo running |
| Kuzu write conflict | Exception | Retry once; log and skip the fact rather than failing the turn |
| Duplicate node explosion | `node_count` growing > 4/turn | Lower `dedup_similarity` from 0.88 to 0.82 |
| System transcribes itself | Self-talk loop | Mic hard-gate during SPEAKING — verify at checkpoint 1 |
| Spectator relay down | `sys.status` | Hide the QR. Zero pipeline impact; the client is write-only. |
| **Total live demo failure** | — | Switch to `replay` adapter. State plainly the room is too noisy and this is a session recorded earlier. If that fails, the backup video. |

---

## 23. Acceptance tests

Go/no-go gates, in order.

| # | Test | Pass criterion |
|---|---|---|
| A1 | `check_stimulus.py` on Machine A, 30 s | Measured refresh within 0.5 Hz of nominal, profile `hi`, zero dropped frames, interval σ < 0.5 ms |
| A2 | `pytest tests/test_fbcca.py` | ≥95% on 200 synthetic windows at 3 µV; ≤2% false positive with no target |
| A3 | `pytest tests/test_profiles.py` | Both sets pass the harmonic-collision matrix; both classify ≥95%; alpha false positives on `lo` land only on `cancel_idx` |
| A4 | `pytest tests/test_telemetry.py` | 10,000 `emit()` with a stalled consumer complete in <50 ms; nothing raises |
| A5 | **Keyboard end-to-end** | With `input.adapter: keyboard` and no hardware attached, a full turn completes: utterance → intents → selection → candidates → selection → audio → bloom |
| A6 | **Offline boot** | With an empty `.env`, the backend starts and a full turn completes on fallback providers |
| A7 | Idle state | Cap on, pilot looking at the wall for 60 s, zero selections |
| A8 | Live classification | 20 cued trials, ≥85% correct target |
| A9 | Latency | Selection → first audio ≤ 2.5 s uncached, ≤ 300 ms cached |
| A10 | Partner conditioning | Same utterance and intent, two partners, two audibly different sentences with the right term of address |
| A11 | Writeback | A novel fact mentioned in conversation appears as a node within one turn and is retrievable in the next |
| A12 | Recovery | Kill the backend mid-turn; restart; dashboard reconnects, graph intact |
| A13 | Replay | A recorded session replays through the real classifier and reproduces the same selections, badge visible |
| A14 | Cross-machine | `scripts/smoke_machine_a.py` passes from a clean clone |
| A15 | Analytics | After 20 cued trials the panel shows a non-empty accuracy series and five distinct per-target sparklines |
| A16 | Spectator | A phone on cellular data loads the domain and shows selections within 2 s |
| A17 | Spectator privacy | Inspect outbound payloads: no raw EEG, no graph node text, no keys |
| A18 | **Local Mode with the network physically off** | Full turn completes, spoken in the Piper voice, graph updated, no exceptions |
| A19 | Purge | `purge {scope:"all"}` empties graph and telemetry; dashboard returns to onboarding |

---

## 24. Assumptions

| # | Item | Default |
|---|---|---|
| 1 | Montage | O1, Oz, O2, POz, PO3, PO4, Pz, CPz; SRB/BIAS on earlobes |
| 2 | Speller scope | Contrast feature, ~2 h, cut first after eTRCA |
| 3 | Machine A ↔ B link | Direct ethernet or dedicated hotspot. **Never venue wifi.** |
| 4 | Deepgram key | Free tier. If unavailable, `faster-whisper small` on CPU adds ~1.5 s per utterance, acceptable |
| 5 | Presenter | Dev D, since Dev A is the pilot |
| 6 | Persona | Marcus Alvarez, editable at runtime |
| 7 | Voice enrollment | Dev A, 60 s, recorded before the event |
| 8 | Tiger Cloud free tier | Assumed sufficient; otherwise local TimescaleDB in Docker, nothing else changes |
| 9 | Emotiv secondary path | Gated on a feasibility test; not on the critical path |

---

## 25. Credits and prior art

To be reproduced in `CREDITS.md` and referenced in the Devpost submission.

- **Lucid Voice** (UC Berkeley AI Hackathon 2026) — prior art. Its public README was read for architectural patterns: provider abstraction, lazy graceful-degradation service construction, cache-first speech, three-candidate selection. No source code was copied. Input modality, signal processing, stimulus renderer and platform all differ.
- **FBCCA** — Chen et al., *Filter bank canonical correlation analysis for implementing a high-speed SSVEP-based BCI*, J. Neural Eng. 2015.
- **TRCA / eTRCA** — Nakanishi et al., *Enhancing detection of SSVEPs for a high-speed BCI using task-related component analysis*, IEEE TBME 2018.
- **Facility location submodular selection** — Schreiber et al., `apricot`, JMLR 2020.
- Libraries: BrainFlow, PsychoPy, pylsl, SciPy, NumPy, scikit-learn, KuzuDB, sentence-transformers, apricot-select, FastAPI, uvicorn, pydantic, PyZMQ, asyncpg, React, Vite, Tailwind, 3d-force-graph, three.js, uPlot, webrtcvad, sounddevice, Piper, faster-whisper, qrcode.
- Services: Google Gemini, ElevenLabs, Deepgram, Tiger Data, DigitalOcean, GoDaddy Registry.

---

## 26. Submission notes

The Devpost writeup needs **one distinct paragraph per track**, naming the specific component. A judge skimming for their own technology should find it in five seconds. Generic "we used X" lines read as track-farming and are worse than not entering.

| Track | The paragraph is about | Point at |
|---|---|---|
| **Microsoft** | Communication for people with motor neuron disease runs at ~8 wpm against speech's 150. We replaced character spelling with semantic intent selection. **The product has no chat window** — the interface is a flicker grid and a 3D memory graph; AI is one stage of a pipeline, not the experience. | §1, §13 |
| **ElevenLabs** | The user's own voice, cloned from a 60 s clip, restored as the output of a brain-driven pipeline. Cache-first playback so the demo is network-independent. | §15.2 |
| **Gemini** | Four distinct call sites — intent labels, grounded sentences, partner identification, post-turn fact extraction that grows the graph — under strict-JSON contracts with repair retry and a graceful fallback chain. | §12 |
| **Tiger Data** | 250 Hz EEG, 20 scores/s and frame-integrity metrics into hypertables. Continuous aggregates drive a live analytics panel showing accuracy, per-target correlation drift and measured Information Transfer Rate. The write path is a bounded drop-on-overflow queue so the database can never stall a real-time neural pipeline. | §18 |
| **DigitalOcean** | Droplet-hosted spectator relay; judges watch on their phones via a deliberately write-only sanitised stream. Gradient AI is the third link in the LLM chain. | §19 |
| **GoDaddy** | Domain fronting the spectator view. | §19 |
| **Assurant** | A system holding a disabled person's life should show what leaves the machine. Live data-flow ledger, per-turn cost in USD, one-click purge, and a Local Mode demonstrated on stage by disabling the network mid-pitch. | §20 |

**Do not claim a track whose component was cut.** Update the Devpost selections at hour 34 against what actually runs, not against this document.
