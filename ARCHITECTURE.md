# ARCHITECTURE

**Flick — a semantic brain–computer interface for assistive communication.**

This document is the single source of truth for the system. Numeric constants are normative; where a constant is tunable it lives in `config.yaml` (§5) and code reads it from there. No magic numbers in source.

> **Revision 2 (2026-09-27).** Hardware moved from OpenBCI Cyton to **Emotiv EPOC X on the free Cortex tier**, selection moved from simultaneous five-frequency SSVEP to **sequential presentation** (§7), the knowledge graph moved from KuzuDB to **Tiger Data** (PostgreSQL + TimescaleDB + pgvector, §10, §18), and the system runs on **one 165 Hz PC**. Every change is itemised in `CHANGELOG.md`. Code has not caught up yet; §21.2 lists the follow-up work.

---

## 0. How to read this

- §1–§3 define what is being built and how the processes fit together.
- §4–§6 are the contracts: repository layout, configuration, and every message schema. **These are frozen first and everything else depends on them.**
- §7 is the input abstraction and the selection method. Read it before writing any code that consumes a user selection.
- §8–§20 specify each subsystem.
- §21–§26 cover build sequencing, failure handling, acceptance criteria and submission.

---

## 1. Product definition

### 1.1 What it does

A person who cannot speak wears an EEG headset and looks at a screen showing four tiles. A microphone listens to whoever is talking to them. When the conversational partner speaks, speech-to-text transcribes it, and a language model — grounded in a personal memory of the user's life — writes three candidate *intents* onto the tiles. The fourth tile is always Cancel.

The tiles are presented **one at a time**. The user selects the one they want in one of two ways (§7): by firing a single trained brain command while their tile is highlighted (**scan-switch**, the default), or simply by looking at it while it flickers so their visual cortex responds more strongly to it than to the others (**sequential flicker**). The system then retrieves relevant personal facts, generates three full candidate sentences, and presents them for a second selection. The chosen sentence is spoken aloud in a clone of the user's own voice. Afterwards the system extracts new facts from the exchange and grows the memory, rendered live in 3D so observers can watch it think and learn.

The user's memory starts from whatever they, or someone on their behalf, choose to share at onboarding (§14), and every conversation afterwards is recorded and used to keep that profile current (§12.4, §18).

### 1.2 Why it is not a speller

Character-by-character BCI spelling runs at roughly 8 words per minute against speech's 150. Selecting *semantic intent* rather than letters produces a full sentence from two selections. The Speller mode exists as a deliberate contrast so the difference can be demonstrated rather than asserted.

### 1.3 Modes

| Mode | Purpose | Priority |
|---|---|---|
| **Intent** | The product. Two selections per sentence. | P0 |
| **Speller** | Row/column scanning over the alphabet using the same switch. Shown briefly to make the contrast visible. | P2 |

### 1.4 Non-goals

Not built, not specified: VR stimulus delivery, haptic feedback, relay or environmental control, Raspberry Pi involvement, simultaneous multi-frequency SSVEP classification (FBCCA/eTRCA — requires raw EEG, which the free Emotiv tier does not provide), a second display machine, local neural voice cloning, speaker identification by voice embedding, multilingual output, blockchain.

### 1.5 Sponsor alignment

Each integration is load-bearing. Nothing is included solely to claim a track.

| Track | What the system uses it for | Priority |
|---|---|---|
| Best Overall | Automatic | — |
| **Microsoft — What's Missing?** | The interface is a scanning tile row and a 3D memory graph. There is no chat window anywhere in the product; AI is one stage of a pipeline, not the experience. | P0 (framing only) |
| **Tiger Data** | **The only database.** The user's profile and memory graph (relational + pgvector), every conversation turn, the history of what the system learned and when, the Emotiv signal streams and every selection — side by side in one PostgreSQL. Continuous aggregates drive the analytics panel; compression keeps the signal streams on the free tier (§10, §18) | **P0** |
| **ElevenLabs** | Instant voice cloning; the user's restored voice (§15) | P0 |
| **Gemini** | Intent labels, grounded sentences, partner identification, fact extraction, profile seeding (§12) | P0 |
| **DigitalOcean** | Spectator relay droplet; Gradient AI as third LLM fallback (§19) | P2 |
| **GoDaddy Registry** | Domain fronting the spectator view | P2 |
| **Assurant** | Data-flow ledger, per-turn API cost, one-click purge, Local Mode (§20) | P3 |

---

## 2. Decision register

Deviating from any of these requires editing this document first, and adding an entry to `CHANGELOG.md`.

### 2.1 Hardware

| ID | Decision |
|---|---|
| HW-1 | **Emotiv EPOC X, 14 channels, free Cortex tier.** Raw EEG is licence-gated and **not available**. Usable streams: `pow` (band power, 8 Hz), `com` (mental commands, 8 Hz), `fac` (facial expressions, 32 Hz), `dev` (contact quality and battery, 2 Hz), `eq` (EEG quality, 2 Hz). `met` is 0.1 Hz without a licence and is not used. |
| HW-2 | Sensors used: **O1, O2** (occipital, for flicker response) and all 14 for mental commands. EPOC X layout: AF3, F7, F3, FC5, T7, P7, O1, O2, P8, T8, FC6, F4, F8, AF4. The headset has no C3/C4, which limits motor-imagery decoding (§7.7). |
| HW-3 | Saline sensors. Budget 10 minutes for setup and a contact-quality check (`dev` stream, all used sensors green). Rehydrate between sessions. |
| HW-4 | Headset on its own battery over the Emotiv USB receiver or Bluetooth. Check battery in `sys.status` before every demo. |
| HW-5 | **One PC**: 165 Hz panel, RTX 5050. The stimulus runs fullscreen on the built-in panel; the judge dashboard runs in a browser on the same PC, on an external display or projector if one is available. |
| HW-6 | OpenBCI Cyton is a **contingency only** (§8.7). Nothing depends on it. |

### 2.2 Interaction

| ID | Decision |
|---|---|
| UX-1 | Two-round selection: intent → three candidates → speak. |
| UX-2 | **Four targets**, presented sequentially: three semantic, one Cancel. `n_intents` is 3. |
| UX-3 | **Selection method is `scan_switch` by default**, `seq_flicker` as the pure-EEG mode. Both share one stimulus (§9). Final choice is made by the feasibility gate (§7.6). |
| UX-4 | The idle state is real. With no trigger (scan-switch) or no clear winner (sequential flicker), nothing is selected. |
| UX-5 | Flicker frequency is **15.0 Hz**: an exact divisor of 165, 120 and 60 Hz, and inside Emotiv's low-beta band, away from resting alpha. |
| UX-6 | Partner identity inferred by LLM from transcript, with manual override. |
| UX-7 | English only. |

### 2.3 Signal processing

| ID | Decision |
|---|---|
| DSP-1 | **No raw-EEG processing in Flick.** Emotiv's Cortex computes band power and runs the mental-command classifier; Flick consumes their outputs. |
| DSP-2 | Scan-switch trigger: the trained `push` command's power must stay at or above threshold for `hold_s` (§8.3). |
| DSP-3 | Sequential-flicker score: occipital low-beta power in the tail of each slot, z-scored against a rest baseline (§8.4). |
| DSP-4 | Mental-command training uses the Cortex `training` API and is stored in the pilot's Emotiv profile. Training is on **attempted movement of one limb** (§7.3). |
| DSP-5 | Slot onsets are published over ZMQ with wall-clock timestamps. P1, P2 and Cortex share one machine and one clock; LSL is not used. |
| DSP-6 | **Nothing selects until it has received a `stim.profile` message.** |

### 2.4 Software

| ID | Decision |
|---|---|
| SW-1 | Python 3.11, `uv`. |
| SW-2 | Backend FastAPI + uvicorn. Frontend Vite + React + TypeScript + Tailwind. |
| SW-3 | **Memory store: Tiger Data** — PostgreSQL with TimescaleDB and pgvector, on Tiger Cloud. Replaces KuzuDB. One database for profile, graph, conversations and signal telemetry. |
| SW-4 | Embeddings: `all-MiniLM-L6-v2` (384-dim), local, CPU, stored as `vector(384)`. |
| SW-5 | Context curation: facility-location greedy selection, implemented directly in numpy (the `apricot-select` implementation measured 800–900 ms against a 150 ms budget and was dropped). |
| SW-6 | LLM: Gemini primary, provider-swappable. |
| SW-7 | STT: cloud primary, `faster-whisper small` on CPU as fallback. |
| SW-8 | TTS: ElevenLabs primary, Piper local fallback, pre-rendered cache in front of both. |
| SW-9 | The Python stack is CPU-only. The GPU is available but nothing requires it. |
| SW-10 | Memory writeback: LLM auto-extracts facts after each turn, commits above threshold, blooms onto the graph, and logs every change as a `memory_events` row. No decay pass. |
| SW-11 | Persona is created at runtime through an onboarding wizard. A committed fixture exists as fallback. |
| SW-12 | Three OS processes plus the frontend dev server. ZeroMQ between them. |
| SW-13 | Every provider and service is lazily constructed and degrades to a correctly-shaped placeholder. |
| SW-14 | **Telemetry writes are never on the critical path.** Memory-store reads and writes are, and are guarded by an in-process mirror and a write outbox so a slow or unreachable database cannot stall a turn (§10.3). |
| SW-15 | The spectator relay connection is **outbound only**; nothing from it enters the pipeline. |
| SW-16 | A Local Mode switch forces the offline provider chain and serves the memory from the mirror. The system must remain functional with it on. |

### 2.5 Demo integrity

| ID | Decision |
|---|---|
| DEMO-1 | **No hidden manual triggering of selections.** Ever. |
| DEMO-2 | Replay mode plays a real recorded session through the real decision logic, with a persistent on-screen `REPLAY` badge. |
| DEMO-3 | Every non-brain input displays a persistent badge naming what it is: `KEYBOARD INPUT`, `REPLAY`, `SYNTHETIC SIGNAL`, and `MUSCLE TRIGGER (EMG)` when the scan-switch trigger is the facial-expression stream. |
| DEMO-4 | A scripted-prompt key exists for feeding partner utterances when the room is too loud for STT. It bypasses the microphone only, never the selection. |
| DEMO-5 | Every session is recorded to disk automatically. |
| DEMO-6 | **Muscle activity is always visible.** The dashboard shows the facial-expression stream beside the mental-command meter. A mental-command selection that coincides with facial activity above threshold is flagged `contaminated` in the selection, in the database and on screen. |
| DEMO-7 | The pitch says what the signal is: "a trained Emotiv mental command for attempted arm movement", not "reading thoughts". |

---

## 3. Topology

### 3.1 Machine

```
┌────────────────────────────────────────────────────────────────┐
│ THE PC — 165 Hz panel, RTX 5050                                │
│   Emotiv EPOC X ── USB receiver / BT ── EMOTIV Launcher         │
│                                          (Cortex, wss :6868)    │
│   P1  sensor     Cortex bridge + selection decision            │
│   P2  stimulus   vsync-locked tiles, fullscreen, built-in panel │
│   P3  backend    FastAPI, orchestrator, memory, providers      │
│   P4  frontend   Vite dev server → judge dashboard (browser,   │
│                  external display / projector if available)    │
└───────────────┬──────────────────────────┬─────────────────────┘
                │ TLS                      │ outbound WS
         ┌──────▼───────┐           ┌──────▼──────────┐
         │ Tiger Cloud  │           │ Spectator relay │
         │ (Postgres)   │           │ (DO droplet)    │
         └──────────────┘           └─────────────────┘
```

The pilot sees only the P2 stimulus window. Judges see the dashboard.

### 3.2 Processes

| Process | Entry point | Binds | Connects to |
|---|---|---|---|
| **P1 sensor** | `python -m sensor.main` | ZMQ PUB `tcp://127.0.0.1:5555` | ZMQ SUB `5556`, `5557`; Cortex `wss://localhost:6868` |
| **P2 stimulus** | `python -m stimulus.main` | ZMQ PUB `5557` | ZMQ SUB `5556` |
| **P3 backend** | `uvicorn backend.app.main:app --host 0.0.0.0 --port 8000` | HTTP/WS `:8000`, ZMQ PUB `5556` | ZMQ SUB `5555`, `5557`; Tiger Cloud |
| **P4 frontend** | `npm run dev` | HTTP `:5173`, proxies `/api` and `/ws` to `:8000` | — |

P1 now subscribes to P2 directly (`5557`) because it needs slot onsets to attribute triggers and score slots. Model loading, LLM calls, database I/O and TTS synthesis all block for seconds at a time; P1 never shares a process with them.

### 3.3 One turn, end to end

```
partner speaks
  ├─► [P3] VAD → STT → transcript                     → conversation_turns
  ├─► [P3] LLM: identify partner from transcript + known Person nodes
  ├─► [P3] retrieval: embed → pgvector seed → 2-hop expand → select
  ├─► [P3] LLM: three intent labels (+ Cancel)
  ├─► [P3] ZMQ: show_targets ──► [P2] renders tiles
  │         WS: conv.intents ──► dashboard
  ├─► [P2] slot by slot: stim.slot ──► P1, P3
  ├─► [P1] Cortex com / pow → trigger or slot scores ──► dashboard
  ├─► [P1] Selection
  ├─► [P3] retrieval round 2 → LLM: three candidate sentences
  │         WS: graph.activate ──► nodes pulse
  ├─► [P1] second Selection
  ├─► [P3] TTS (cache → ElevenLabs → Piper) → audio
  └─► [P3] LLM: fact extraction → Tiger writeback → memory_events → graph.bloom
```

---

## 4. Repository layout

```
flick/
├── ARCHITECTURE.md
├── CHANGELOG.md                # every change to this document, dated
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
│   ├── bci.py                  # production: consumes P1 over ZMQ (was ssvep.py)
│   └── replay.py               # recorded session through the real decision logic
│
├── sensor/                     # P1
│   ├── main.py
│   ├── sources/
│   │   ├── base.py             # SignalSource ABC
│   │   ├── cortex.py           # Emotiv Cortex JSON-RPC over WebSocket
│   │   ├── synthetic.py        # generates solvable pow / com / fac (§8.5)
│   │   └── replay.py           # recorded .jsonl at real-time pace
│   ├── decision/
│   │   ├── scan_switch.py      # §8.3
│   │   └── seq_flicker.py      # §8.4
│   ├── training.py             # Cortex mental-command training (§8.2)
│   └── recorder.py
│
├── stimulus/                   # P2
│   ├── main.py
│   ├── profile.py              # measure refresh → frames per 15 Hz cycle (§9.2)
│   ├── tiles.py
│   └── integrity.py
│
├── backend/                    # P3
│   ├── app/
│   │   ├── main.py
│   │   ├── orchestrator.py     # conversation FSM (§13)
│   │   ├── ws.py
│   │   └── services/
│   │       ├── db.py           # asyncpg pools: memory + telemetry (§10.3)
│   │       ├── graph.py        # Tiger-backed memory graph (§10)
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
│   │   ├── llm_static.py
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
│           ├── BandPowerPlot.tsx    # uPlot, occipital bands over time
│           ├── HeadsetQuality.tsx   # per-sensor contact, battery
│           ├── SlotPanel.tsx        # tiles, active slot, scores / trigger meter
│           ├── MuscleStrip.tsx      # facial-expression activity (DEMO-6)
│           ├── Transcript.tsx
│           ├── CandidatePanel.tsx
│           ├── StatusBar.tsx
│           ├── SessionAnalytics.tsx
│           ├── MemoryTimeline.tsx   # what was learned, when (§18.5)
│           ├── PrivacyPanel.tsx
│           ├── SpectatorQR.tsx
│           └── BioWizard.tsx
│
├── experiments/
│   └── seq_flicker/            # standalone §7.6 feasibility test (TEST_PLAN.md)
│
├── spectator/                  # deployed to DigitalOcean
│   ├── relay.py
│   ├── static/index.html
│   └── Dockerfile
│
├── migrations/
│   ├── 001_memory.sql          # extensions, profiles, nodes, edges (§10.1)
│   └── 002_timeseries.sql      # hypertables, aggregates, compression (§18.2)
│
├── scripts/
│   ├── enroll_voice.py
│   ├── prerender_cache.py
│   ├── check_cortex.py         # licence-free streams reachable, contact quality
│   ├── train_command.py        # neutral + push training via Cortex
│   ├── run_cued_block.py
│   ├── feasibility.py          # the §7.6 gate
│   ├── check_stimulus.py
│   ├── fake_sensor.py          # dashboard dev tool (exists)
│   ├── seed_tiger.py
│   └── smoke.py
│
└── tests/
    ├── test_schemas.py
    ├── test_inputs.py
    ├── test_scan_switch.py
    ├── test_seq_flicker.py
    ├── test_stimulus_profile.py
    ├── test_graph.py           # against a disposable Postgres
    ├── test_retrieval.py
    ├── test_telemetry.py
    └── ...                     # existing service tests
```

---
## 5. Configuration

`config.yaml`, loaded by `shared/config.py`. Secrets live in `.env` and never in `config.yaml`.

```yaml
input:
  adapter: keyboard          # keyboard | bci | replay
  replay_file: null

mode:
  source: synthetic          # emotiv | synthetic | replay   (sensor process)
  selection: scan_switch     # scan_switch | seq_flicker
  trigger: mental_command    # mental_command | facial     (scan_switch only)
  targets: 4                 # 3 semantic + Cancel

emotiv:
  cortex_url: wss://localhost:6868
  profile: flick-pilot       # Emotiv training profile name
  headset_id: auto
  streams: [pow, com, fac, dev, eq]
  occipital_sensors: [O1, O2]
  min_contact_quality: 3     # dev stream, 0..4; below this a sensor is flagged

stimulus:
  expected_refresh_hz: 165
  flicker_hz: 15.0           # exact divisor of 165, 120 and 60
  contrast: 0.85
  tile_layout: row
  tile_px: 300
  tile_gap_px: 120
  label_font_px: 34
  cue_duration_s: 1.5        # labels shown, nothing moving, before the first slot
  integrity_drop_threshold: 5
  cancel_idx: 3
  scan:
    slot_s: 2.0
    max_cycles: 3            # then timeout → IDLE
    flicker_active: true     # the highlighted tile also flickers
  seq_flicker:
    slot_s: 4.0              # Cortex pow covers the last 2 s, so a slot must exceed 2 s
    gap_s: 1.0
    max_cycles: 2            # stop after cycle 1 if the margin is already met
    randomize_order: true

decision:
  scan_switch:
    command: push
    power_threshold: 0.45    # com power, 0..1
    hold_s: 0.5              # 4 consecutive com samples at 8 Hz
    latency_comp_s: 0.3      # attribute the trigger to the slot active this long before its onset
    refractory_s: 1.5
    facial_action: clench    # used when mode.trigger = facial
    facial_threshold: 0.5
    contamination_threshold: 0.3   # fac power that marks a com trigger contaminated
  seq_flicker:
    band: betaL              # 12–16 Hz on Emotiv's pow stream
    score_tail_s: 2.0        # slot_s − 2 s: where the 2 s pow window lies inside the slot
    baseline_s: 20
    z_threshold: 1.0
    margin_ratio: 1.3

calibration:
  neutral_trials: 3          # 8 s each, Cortex training
  command_trials: 5
  cued_block_trials: 20

database:
  memory_pool_max: 5
  telemetry_pool_max: 3
  query_timeout_s: 0.3       # memory reads; on timeout, serve from the mirror
  write_timeout_s: 1.0
  outbox_retry_s: 5.0

graph:
  profile_id: user
  embedding_dim: 384

retrieval:
  vector_top_k: 25
  hops: 2
  candidate_cap: 60
  select_k: 8

generation:
  n_intents: 3
  n_candidates: 3
  max_tokens: 400
  timeout_s: 6.0

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
  bandpower_downsample: 1
  compress_after: 10m

spectator:
  enabled: true
  url: wss://<domain>/producer
  throttle_hz: 1.0
  send_signal: false         # NEVER true
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

TIGER_DSN=
LOCAL_PG_DSN=

EMOTIV_CLIENT_ID=
EMOTIV_CLIENT_SECRET=

SPECTATOR_URL=
SPECTATOR_TOKEN=

DEMO_REPLAY=false
LOCAL_MODE=false
```

`TIGER_DSN` is the Tiger Cloud service connection string. `LOCAL_PG_DSN` points at a local `timescale/timescaledb-ha` container (it bundles pgvector) and is used by tests and by anyone developing offline.

**Provider fallback chains** (`providers/registry.py`). Each link is skipped if its key is absent or its last call failed within 30 s:

- LLM: `gemini` → `openai_compat` → `do_gradient` → `static`
- STT: `deepgram` → `faster_whisper` → `manual`
- TTS: `cache` → `elevenlabs` → `piper` → `browser SpeechSynthesis`

**The last link in every chain never touches the network.** The backend therefore boots and serves a complete, correctly-shaped turn with no API keys at all. With no `TIGER_DSN` either, the memory is loaded from the fixture into the mirror (§10.3) and writes stay in the outbox.

**Local Mode** truncates every provider chain to its offline links, serves memory reads from the mirror and holds memory writes in the outbox, disables the spectator relay and pauses telemetry uploads. Toggling requires no restart.

---

## 6. Contracts

All schemas live in `shared/schemas.py` as pydantic v2 models, mirrored by hand in `frontend/src/lib/types.ts`. Every message carries `type` and `ts` (float, UNIX seconds).

**These are frozen before any other work starts.** Everything in the system depends on them. Revision 2 changes §6.1, §6.2, §6.4, §6.5 and §6.6; the code must follow AGENTS.md §4 to adopt them.

### 6.1 The selection contract

The single most important type in the system. Everything upstream of it is replaceable.

```python
class Selection(BaseModel):
    type: Literal["input.selection"]
    ts: float
    trial_id: str                    # must match the current trial or it is dropped
    target_idx: int                  # 0..n_targets-1
    confidence: float                # 0..1, adapter-defined
    source: str                      # "bci" | "keyboard" | "replay"
    algorithm: str | None            # "scan_switch" | "seq_flicker" | None
    trigger: str | None = None       # "mental_command" | "facial" | None
    contaminated: bool = False       # DEMO-6
```

### 6.2 ZMQ: P1 sensor → P3 backend (`bci.` prefix)

```python
class BandPowerFrame(BaseModel):    # 8 Hz, from Cortex pow
    type: Literal["bci.bandpower"]
    ts: float
    sensors: list[str]               # the 14 EPOC X sensors, Cortex order
    bands: list[str]                 # ["theta","alpha","betaL","betaH","gamma"]
    power: list[list[float]]         # [n_sensors][5], Cortex units

class CommandFrame(BaseModel):      # 8 Hz, from Cortex com + fac
    type: Literal["bci.command"]
    ts: float
    action: str                      # "neutral" | "push" | ...
    power: float                     # 0..1
    facial_action: str | None        # strongest current fac action
    facial_power: float              # 0..1, max over fac samples since last frame

class SlotScores(BaseModel):        # every pow sample during a trial
    type: Literal["bci.slot_scores"]
    ts: float
    trial_id: str
    algorithm: Literal["scan_switch", "seq_flicker"]
    active_slot: int | None
    cycle: int
    scores: list[float | None]       # seq_flicker: z-score per target so far; scan_switch: None
    trigger_power: float | None      # scan_switch: current com power
    hold_count: int                  # consecutive qualifying samples
    winner_idx: int | None
    margin: float | None

class SensorSelection(BaseModel):   # topic "bci.selection", event
    """Emitted by P1 when its decision logic fires. The `bci` input
    adapter (§7.2) maps this onto the generic `Selection` of §6.1."""
    type: Literal["bci.selection"]
    ts: float
    trial_id: str
    target_idx: int
    score: float                     # trigger power, or winner z-score
    margin: float | None
    algorithm: Literal["scan_switch", "seq_flicker"]
    trigger: Literal["mental_command", "facial"] | None
    contaminated: bool

class SensorStatus(BaseModel):      # 1 Hz
    type: Literal["bci.status"]
    ts: float
    source: Literal["emotiv", "synthetic", "replay"]
    connected: bool
    configured: bool                 # has a stim.profile been received?
    headset_id: str | None
    battery_pct: int | None
    contact_quality: dict[str, int]  # sensor → 0..4, from dev
    eeg_quality: float | None        # from eq
    profile_loaded: bool             # Emotiv training profile active
    trained_actions: list[str]
    dropped_samples: int
```

### 6.3 WebSocket: dashboard → P3 (`client.` prefix)

The only inbound channel. Everything else the dashboard sends goes over REST (§6.8); this exists for input that must be low-latency and ordered with the outbound stream.

```python
class KeyPress(BaseModel):
    """Drives the `keyboard` input adapter (§7.4). Keys outside the
    configured target count are dropped."""
    type: Literal["client.key_press"]
    ts: float
    key: str                         # "1".."4"

class RequestSnapshot(BaseModel):
    """Sent on every (re)connect. P3 replies with graph.snapshot and one
    sys.status so a reconnecting dashboard is immediately consistent."""
    type: Literal["client.request_snapshot"]
    ts: float
```

Inbound messages that fail validation are logged and dropped. The dashboard is never trusted to drive anything destructive; purge, mode changes and adapter swaps are REST endpoints so they are explicit and auditable.

### 6.4 ZMQ: P3 → P2 stimulus (`stim.` prefix)

```python
class ShowTargets(BaseModel):
    type: Literal["stim.show_targets"]
    ts: float
    trial_id: str
    labels: list[str]                # n_targets, Cancel last
    round: Literal["intent", "candidate", "speller"]
    cue_idx: int | None              # cued blocks only

class StimControl(BaseModel):
    type: Literal["stim.control"]
    ts: float
    action: Literal["idle", "start", "stop", "confirm", "message"]
    target_idx: int | None           # confirm: flash the selected tile
    message: str | None
```

### 6.5 ZMQ: P2 → P1, P3 (`stim.` prefix)

```python
class StimulusProfile(BaseModel):
    """Published at startup after measuring the real refresh rate."""
    type: Literal["stim.profile"]
    ts: float
    measured_refresh_hz: float
    flicker_hz: float
    frames_per_cycle: float          # 11.0 at 165 Hz, 4.0 at 60 Hz
    exact: bool                      # frames_per_cycle within 1% of an integer
    selection: Literal["scan_switch", "seq_flicker"]
    slot_s: float
    gap_s: float
    n_targets: int
    cancel_idx: int

class StimulusSlot(BaseModel):
    """One per slot, published in the frame the slot starts."""
    type: Literal["stim.slot"]
    ts: float
    trial_id: str
    cycle: int
    slot_idx: int                    # position in this cycle's order
    target_idx: int                  # which tile is active
    flicker: bool
    duration_s: float

class StimulusIntegrity(BaseModel):
    type: Literal["stim.integrity"]
    ts: float
    measured_refresh_hz: float
    dropped_frames_last_s: int
    frame_interval_std_ms: float
```

### 6.6 WebSocket: P3 → dashboard

Envelope `{"type": ..., "ts": ..., "payload": {...}}`.

| `type` | Rate | Payload |
|---|---|---|
| `eeg.bandpower` | 4 Hz | `{sensors, bands, power}` (P3 downsamples P1's 8 Hz) |
| `bci.command` | 8 Hz | mirrors `CommandFrame` |
| `bci.slot_scores` | 8 Hz during trials | mirrors `SlotScores` |
| `stim.slot` | event | `{trial_id, cycle, target_idx, flicker}` |
| `input.selection` | event | `{target_idx, label, round, confidence, source, algorithm, trigger, contaminated}` |
| `conv.transcript` | event | `{speaker, text, partner_id, partner_name, confidence}` |
| `conv.intents` | event | `{trial_id, labels}` |
| `conv.candidates` | event | `{trial_id, candidates, grounding}` |
| `conv.spoken` | event | `{text, voice, cached, latency_ms}` |
| `graph.snapshot` | on connect | `{nodes, edges}` |
| `graph.activate` | event | `{node_ids, edge_ids, reason}` |
| `graph.bloom` | event | `{nodes, edges}` |
| `fsm.state` | event | `{state, detail}` |
| `sys.status` | 1 Hz | `{input_source, input_badge, source, connected, replay, local_mode, selection, measured_refresh_hz, battery_pct, contact_quality, profile_loaded, providers, stimulus_integrity, memory_store, telemetry_dropped}` |
| `analytics.summary` | 2 s | `{accuracy_pct: float \| null, itr_bits_per_min: float \| null, cued_trials: int, mean_score_by_target, selections_total, mean_selection_latency_s, contaminated_pct, facts_learned_last_10m}` |
| `privacy.flow` | event | `{stage, destination, bytes, description}` |
| `privacy.cost` | event | `{turn_id, items, turn_usd, session_usd}` |
| `spectator.link` | on connect | `{url, connected_viewers}` |

`sys.status.memory_store` is `"tiger" | "mirror" | "fixture"` so the dashboard shows when the memory is being served from cache.

### 6.7 Graph payload types

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

**`label` derivation.** Every node except `Memory` has `name`; `Memory` has `text`. `GraphService.snapshot()` derives:

```python
label = row["name"] or row["text"][:60]
```

Memory text is truncated to 60 characters because it is rendered on a 3D node, not read. The `nodes` table's CHECK constraint (§10.1) guarantees one of the two is present.

### 6.8 REST

| Method | Path | Body | Purpose |
|---|---|---|---|
| `GET` | `/api/health` | — | liveness + provider + database status |
| `GET` | `/api/graph` | — | full snapshot |
| `POST` | `/api/onboarding/seed` | `{bio, name}` | bio → seeded memory |
| `GET` | `/api/onboarding/status` | — | `{seeded, node_count}` |
| `POST` | `/api/partner` | `{partner_id}` | manual override |
| `POST` | `/api/utterance` | `{text}` | scripted-prompt advance |
| `POST` | `/api/mode` | `{mode}` | intent \| speller |
| `POST` | `/api/input` | `{adapter}` | hot-swap the input adapter |
| `POST` | `/api/selection_method` | `{selection, trigger}` | scan_switch \| seq_flicker; mental_command \| facial |
| `POST` | `/api/training/start` | `{action, trials}` | Cortex training: `neutral` or `push` |
| `GET` | `/api/training/status` | — | trained actions, last training time |
| `POST` | `/api/cued_block/start` | `{n_trials}` | run cued trials (§18.6) |
| `GET` | `/api/session/latest` | — | most recent recording |
| `GET` | `/api/analytics/summary` | — | continuous-aggregate rollup |
| `GET` | `/api/memory/timeline` | `?since=` | memory_events, newest first (§18.5) |
| `POST` | `/api/privacy/local_mode` | `{enabled}` | toggle, no restart |
| `GET` | `/api/privacy/flows` | — | what has left the machine |
| `POST` | `/api/privacy/purge` | `{scope}` | delete stored personal data |
| `GET` | `/api/spectator/link` | — | public URL + QR payload |

---
## 7. The input layer

**This is the abstraction that decouples every other subsystem from the headset.** Nothing downstream of `InputSource` knows or cares how a selection was produced — which is why the hardware change in revision 2 touches P1, P2 and this section, and nothing in the conversation pipeline.

### 7.1 Interface

`inputs/base.py` (unchanged):

```python
class InputSource(ABC):
    name: str                        # "keyboard", "bci", "replay"
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
        """Present n_targets options."""

    @abstractmethod
    def selections(self) -> AsyncIterator[Selection]:
        """Yields at most one Selection per trial_id."""

    def status(self) -> dict:
        """Adapter-specific health, merged into sys.status."""
        return {}
```

The orchestrator (§13) holds exactly one `InputSource`. Swapping adapters is a config change or a `POST /api/input`; no other code changes.

### 7.2 `bci` — the production adapter

Renamed from `ssvep`. Subscribes to `SensorSelection` (`bci.selection`, §6.2) on ZMQ 5555 and maps it onto `Selection` with `source: "bci"`, carrying `score` through as `confidence` (clamped to 0..1), and `algorithm`, `trigger` and `contaminated` through unchanged. Calls `set_targets` by publishing `stim.show_targets` on 5556.

`badge` is `None` when the selection method is `seq_flicker`, or `scan_switch` with `trigger: mental_command`. It is **`MUSCLE TRIGGER (EMG)`** when `trigger: facial` (DEMO-3).

### 7.3 The selection methods

Both methods use **sequential presentation**: the four tiles are shown with their labels, then activated one at a time. They differ in what decides the selection.

**`scan_switch` (default).** The active tile is highlighted (and flickers at 15 Hz when `flicker_active`). The user fires one trained mental command — `push`, trained on *attempted movement of one arm* — while their tile is active. P1 attributes the trigger to the tile that was active `latency_comp_s` before the trigger's onset. If no trigger arrives in `max_cycles` passes, the trial times out to IDLE.

This is **switch scanning**, the standard access method in augmentative communication for people with a single reliable movement, and the method used by an implanted-BCI ALS participant who spelled by attempting a hand grasp as a click (Candrea et al., 2024). Detecting one command against rest is far easier than telling several apart, which is why it is the default.

**`seq_flicker` (pure-EEG mode).** Only the active tile flickers. Every tile flickers at the **same** 15 Hz, so no frequency discrimination is needed — which is the point, because band power cannot separate 8 Hz from 9.6 Hz. The user keeps looking at the tile they want; when that tile is active, it is on the fovea and the occipital 15 Hz response is at its strongest. P1 compares occipital low-beta power across the slots and picks the strongest if it clears threshold and margin.

It is slower (≈20 s for one pass of four slots at 4 s + 1 s gap) and its accuracy on free-tier band power is unproven, so it is gated (§7.6). Its value is that it involves no muscle and no training: everything a judge sees is visual cortex.

**Speller** uses `scan_switch` over a row/column grid. `seq_flicker` is never used for the speller — it is too slow per decision.

### 7.4 `keyboard` — the development adapter

Listens for number keys 1–4 in the dashboard and emits a `Selection` with `confidence: 1.0` and `source: "keyboard"`. Dashboard shows a persistent orange **`KEYBOARD INPUT`** badge (DEMO-3).

With this adapter the full conversational pipeline — STT, retrieval, generation, TTS, memory writeback, every visualisation — is buildable and testable with no headset. It is a development tool. It is never used in front of judges.

### 7.5 `replay` — the demo fallback

Drives the sensor process's `replay` source, so a recorded session's Cortex streams flow through the **real decision logic** and produce genuine selections. Badge: **`REPLAY — recorded HH:MM`**.

This is the honest crash insurance (DEMO-1, DEMO-2). If the live demo fails, say so and show a session recorded an hour ago. Every number a judge sees is real.

### 7.6 Feasibility gate

Run `scripts/feasibility.py` with the pilot wearing the headset, as early as possible. It runs 20 cued trials per method with four targets (chance = 25%) and prints accuracy, a binomial p-value, mean selection time and the contaminated fraction.

| Result | Decision |
|---|---|
| `scan_switch` (mental command) ≥ 80%, p < 0.05, contaminated < 20% | Production default. |
| `scan_switch` (mental command) fails | Retrain once (§8.2). If it still fails, use `trigger: facial` with the `MUSCLE TRIGGER (EMG)` badge — honest, and still a real assistive method. |
| `seq_flicker` ≥ 60%, p < 0.05 | Offered as the pure-EEG mode in the demo. |
| `seq_flicker` fails | Dropped from the demo; mentioned in the pitch as tested. |

Record the numbers in `CHANGELOG.md`. The pitch quotes these measured numbers and nothing else.

`experiments/seq_flicker/` implements the `seq_flicker` half of this gate as a standalone tool (three tiles, blocked runs, baseline, signal check and control run); its `TEST_PLAN.md` holds the protocol and pass rules. With three tiles, chance is 33% and the bar is the same ≥ 60%, p < 0.05.

### 7.7 Experimental: two-command attempted movement

Left arm vs right arm (or legs) as two separate commands, with tied limbs for the demo. **Not on the critical path, not built unless both gates above pass with time to spare.** Two reasons:

- The EPOC X has no C3/C4, where hand motor activity is normally read. A 2025 study of multiclass motor imagery on the EPOC X measured test accuracy of 17–36% — near chance.
- A tied-up person attempting to move tenses jaw, neck and face. Emotiv's classifier can learn that muscle activity. DEMO-6 would flag it, which is correct, but it undermines the claim.

A single command (§7.3) keeps the attempted-movement story with a far better chance of working. If a Cyton becomes available, §8.7 covers the upgrade path.

### 7.8 Badge rule

`sys.status.input_badge` is rendered by `StatusBar.tsx` in high contrast whenever non-null. Only the `bci` adapter using `seq_flicker` or a mental-command trigger has a null badge. This is how DEMO-1 and DEMO-3 are enforced in code rather than in discipline.

---

## 8. Sensor process (P1)

### 8.1 Cortex connection

`sources/cortex.py` speaks Cortex's JSON-RPC over `wss://localhost:6868` (served by the EMOTIV Launcher). Startup sequence, each step logged:

1. `requestAccess` → `authorize` (client id/secret from `.env`) → cortex token
2. `queryHeadsets`; `controlDevice` `connect` if needed; pick `emotiv.headset_id` or the first
3. `createSession` (active)
4. `setupProfile` `load` for `emotiv.profile` (needed for meaningful `com`)
5. `subscribe` to `emotiv.streams`

A dedicated asyncio task reads the socket and does nothing else — no decision logic, no I/O. Samples go onto an in-process queue. On failure at any step, log and fall back to `synthetic` with a loud warning and the `SYNTHETIC SIGNAL` badge.

Streams and their use:

| Stream | Rate | Used for |
|---|---|---|
| `pow` | 8 Hz | `seq_flicker` scoring; dashboard band-power plot; telemetry |
| `com` | 8 Hz | `scan_switch` trigger |
| `fac` | 32 Hz | `facial` trigger; contamination flag (DEMO-6) |
| `dev` | 2 Hz | contact quality per sensor, battery |
| `eq` | 2 Hz | overall signal quality |

`pow` values are in Cortex's own units. Nothing compares them across sessions; `seq_flicker` z-scores them against the session's own baseline.

### 8.2 Mental-command training

`training.py` wraps the Cortex `training` method: `start` → Cortex runs an 8 s recording → `accept`. `scripts/train_command.py` and `POST /api/training/start` drive it.

Protocol, about 10 minutes:

1. `neutral` × `neutral_trials`: relaxed, eyes on the screen, **face slack**
2. `push` × `command_trials`: attempt to move the right arm against the restraint, **face slack**
3. Save the profile

Say "face slack" out loud before every `push` trial. The classifier learns whatever differs between neutral and push; if the jaw clenches during push, it learns the jaw. DEMO-6 exists to catch this.

### 8.3 `scan_switch` decision

```
IDLE ──(stim.slot for a trial)──► ARMED
ARMED ──(com.action == command and com.power >= power_threshold)──► HOLD(1)
HOLD(n) ──(still qualifying)──► HOLD(n+1)
HOLD(n) ──(not qualifying)──► ARMED
HOLD(hold_s × 8) ──► emit SensorSelection ──► REFRACTORY
REFRACTORY ──(refractory_s elapsed)──► ARMED or IDLE
```

- **Attribution.** `t_onset` is the timestamp of the first sample of the qualifying run. The selected target is the one whose `stim.slot` was active at `t_onset − latency_comp_s`.
- **Facial trigger.** With `mode.trigger: facial`, the same machine runs on `fac` with `facial_action` / `facial_threshold`.
- **Contamination.** A mental-command selection is `contaminated` if any `fac` sample during the hold run has power ≥ `contamination_threshold`. It is still emitted — hiding it would be worse — but flagged everywhere.

### 8.4 `seq_flicker` decision

1. **Baseline.** At session start, and after each cued block, record `baseline_s` of eyes-open rest. Per occipital sensor, store the mean and standard deviation of `band` power.
2. **Per slot.** Average `band` power over O1 and O2 for the pow samples in the final `score_tail_s` of the slot. Cortex computes each pow sample from the **last 2 s** of EEG (Cortex API docs), so only samples at least 2 s after onset see the slot alone; with a 4 s slot that is 2 s, 16 samples. Convert log power to z against the baseline.
3. **Per target.** Mean of that target's slot z-scores across cycles so far.
4. **Decide** after each cycle: winner = argmax. Select if `z[winner] ≥ z_threshold` **and** `z[winner] − z[second] ≥ margin_ratio − 1` in baseline standard deviations. Otherwise run another cycle, up to `max_cycles`, then no selection.

Both conditions are required, for the same reason as before: noise pushes several slots up together, and the margin test is what makes the idle state credible.

`gap_s` between slots is blank so the band-power window can settle.

### 8.5 Synthetic source

Must produce data the real decision logic has to work for:

- **pow**: log-normal band power per sensor with a slow random walk; alpha elevated and variable. When a target is attended and its tile is flickering, occipital betaL rises by a configurable effect size (default 0.8 baseline SD) ramping over 600 ms; other sensors unchanged.
- **com**: `neutral` with power noise around 0.1; when a synthetic intent fires, `push` power ramps to 0.7 for 0.8 s. Occasional spurious `push` spikes shorter than `hold_s`.
- **fac**: random blinks; optional jaw-clench episodes, some overlapping `push`, so the contamination flag is exercised.

Exposes `set_attended_target(idx | None)` and `fire_command()`. `tests/test_scan_switch.py` and `tests/test_seq_flicker.py` assert ≥95% correct attribution on synthetic data and ≤2% selections with no intent.

### 8.6 Recorder

Always on. Writes `data/sessions/{ISO8601}.jsonl`: every Cortex sample as received, every `stim.slot`, every selection, and a JSON sidecar of the config in force. Directly loadable by `sources/replay.py`; this is what makes DEMO-2 possible.

### 8.7 Contingency: OpenBCI Cyton

If the gates in §7.6 fail and a Cyton is available: add `sources/cyton.py` (BrainFlow, 250 Hz raw) and a raw-EEG scorer for `seq_flicker` that uses canonical correlation at 15 Hz and its harmonics on O1/Oz/O2 instead of band power. Everything above the `SensorSelection` contract stays as it is. Not specified further unless triggered.

---

## 9. Stimulus process (P2)

### 9.1 Rendering

PsychoPy `visual.Window(fullscr=True, waitBlanking=True, useFBO=True, winType='pyglet')` on the 165 Hz panel. Vsync-locked; one `win.flip()` per loop iteration.

Luminance of a flickering tile is a sinusoid sampled at frame boundaries:

```
L(n) = 0.5 * (1 + contrast * sin(2π · flicker_hz · n / refresh_hz))
```

At 165 Hz, 15 Hz is exactly 11 frames per cycle; at 60 Hz it is exactly 4. The sinusoid keeps the energy at the fundamental.

### 9.2 Refresh check

`profile.py` runs before the first trial:

1. Render 300 blank frames, discarding the first 60
2. `measured_refresh_hz = 1 / median_frame_interval`
3. `frames_per_cycle = measured_refresh_hz / flicker_hz`; `exact` if within 1% of an integer
4. Publish `stim.profile`

**Do not trust what the OS reports.** A panel set to 165 Hz delivering 60 because of a power profile or a display cable is a failure that looks exactly like a bad signal. 15 Hz stays exact at 60 and 120 Hz too, so a lower refresh still works — but log a WARNING whenever the measured rate is not `expected_refresh_hz`.

### 9.3 Tile layout

```
┌────────┐   ┌────────┐   ┌────────┐   ┌────────┐
│ TILE 0 │   │ TILE 1 │   │ TILE 2 │   │ CANCEL │
└────────┘   └────────┘   └────────┘   └────────┘
```

A single row reads left to right, which is the order of a scan. Each tile is `tile_px` square with `tile_gap_px` between tiles to limit spatial crosstalk. Labels are rendered at **constant luminance** — text never flickers. The active tile gets a bright border in both methods.

### 9.4 Trial sequence

1. Receive `stim.show_targets`; render labels on static tiles
2. `cue_duration_s` with nothing moving, so the pilot can read and decide
3. For each cycle and each slot in order (fixed for `scan_switch`, shuffled per cycle for `seq_flicker` when `randomize_order`): highlight, start flicker if applicable, publish `stim.slot` in the same frame, hold for `slot_s`, then `gap_s` blank
4. Continue until `stop`, or `max_cycles` is reached
5. On `confirm`, show the selected tile solid for 400 ms, return to idle

For cued blocks, the cued tile has a distinct outline during the cue phase.

### 9.5 Integrity monitoring

`integrity.py` records every flip interval and publishes `stim.integrity` once per second: measured refresh, count of intervals exceeding 1.5× nominal, and interval standard deviation. Over `integrity_drop_threshold` drops in one second logs at ERROR.

`scripts/check_stimulus.py` runs the loop standalone for 30 s and prints a pass/fail verdict. Run it at hour 0, with the GPU driver set to the discrete GPU for Python, and the panel at 165 Hz.

---
## 10. Memory store — Tiger Data

The user's profile and memory graph live in PostgreSQL on Tiger Cloud, in the same database as the conversation history and signal telemetry (§18). It replaces KuzuDB.

### 10.1 Schema

`migrations/001_memory.sql`:

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE profiles (
  id           TEXT PRIMARY KEY,               -- "user"
  display_name TEXT NOT NULL,
  bio          TEXT,                           -- what was shared at onboarding
  shared_by    TEXT,                           -- self, or who shared it on their behalf
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE nodes (
  id            TEXT PRIMARY KEY,
  profile_id    TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL CHECK (kind IN
                  ('Person','Place','Thing','Activity','Need','Memory')),
  name          TEXT,
  text          TEXT,
  attrs         JSONB NOT NULL DEFAULT '{}',   -- relationship, address_terms, category,
                                               -- time_of_day, urgency, occurred_on,
                                               -- source, notes
  embedding     vector(384) NOT NULL,
  weight        DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_accessed TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((kind = 'Memory' AND text IS NOT NULL) OR (kind <> 'Memory' AND name IS NOT NULL)));

CREATE INDEX nodes_profile ON nodes (profile_id, kind);
CREATE INDEX nodes_embedding ON nodes USING hnsw (embedding vector_cosine_ops);

CREATE TABLE edge_rules (                      -- the allowed (kind, from, to) triples
  kind     TEXT NOT NULL,
  src_kind TEXT NOT NULL,
  dst_kind TEXT NOT NULL,
  PRIMARY KEY (kind, src_kind, dst_kind));

INSERT INTO edge_rules VALUES
  ('KNOWS','Person','Person'),
  ('LIKES','Person','Thing'), ('LIKES','Person','Activity'),
  ('LIKES','Person','Place'), ('LIKES','Person','Person'),
  ('DISLIKES','Person','Thing'), ('DISLIKES','Person','Activity'),
  ('DISLIKES','Person','Place'),
  ('NEEDS','Person','Need'), ('NEEDS','Person','Thing'),
  ('LOCATED_AT','Thing','Place'), ('LOCATED_AT','Activity','Place'),
  ('LOCATED_AT','Person','Place'),
  ('DOES','Person','Activity'),
  ('INVOLVES','Memory','Person'), ('INVOLVES','Memory','Place'),
  ('INVOLVES','Memory','Thing'), ('INVOLVES','Memory','Activity'),
  ('RELATES_TO','Thing','Thing'), ('RELATES_TO','Activity','Activity'),
  ('RELATES_TO','Thing','Activity'), ('RELATES_TO','Need','Thing');

CREATE TABLE edges (
  id              TEXT PRIMARY KEY,
  profile_id      TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  kind            TEXT NOT NULL,
  src             TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  dst             TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  weight          DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  count           BIGINT NOT NULL DEFAULT 1,
  strength        DOUBLE PRECISION,              -- LIKES / DISLIKES only, 0..1
  last_reinforced TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (kind, src, dst));

CREATE INDEX edges_src ON edges (src);
CREATE INDEX edges_dst ON edges (dst);
```

Node kinds, edge kinds and the allowed pairs are the same as the Kuzu schema they replace. Kind-specific columns moved into `attrs` so one table holds every kind; `GraphService.upsert_edge` checks `edge_rules` before inserting.

`LIKES` and `DISLIKES` stay separate edge kinds rather than one signed edge: the LLM emits these far more reliably than a numeric valence, and `strength` carries intensity where it matters.

The user is a `Person` with `id = "user"` and `attrs.relationship = "self"`. Everything hangs off that.

### 10.2 Operations

```python
class GraphService:
    async def ensure_schema(self) -> None           # runs the migrations if absent
    async def seed_from_json(self, payload: dict) -> SeedResult
    def snapshot(self) -> tuple[list[GraphNode], list[GraphEdge]]   # from the mirror
    async def vector_search(self, q: np.ndarray, k: int) -> list[NodeRef]
    async def expand(self, seeds: list[NodeRef], hops: int, cap: int) -> list[NodeRef]
    async def reinforce(self, node_ids: list[str], edge_ids: list[str], turn_id: str) -> None
    async def upsert_node(self, kind: str, props: dict, turn_id: str | None) -> str
    async def upsert_edge(self, kind: str, src: str, dst: str, props: dict,
                          turn_id: str | None) -> str
    def people(self) -> list[Person]
    def node_count(self) -> int
    async def purge(self) -> None
```

Every write also appends a `memory_events` row (§18.2). That table is the profile's history: what was learned, from which turn, with what confidence.

`vector_search` is pgvector:

```sql
SELECT id, kind, 1 - (embedding <=> $1) AS similarity
FROM nodes
WHERE profile_id = $2
ORDER BY embedding <=> $1
LIMIT $3;
```

`expand` is a recursive CTE, undirected, depth-limited:

```sql
WITH RECURSIVE walk(node_id, depth) AS (
    SELECT unnest($1::text[]), 0
  UNION
    SELECT CASE WHEN e.src = w.node_id THEN e.dst ELSE e.src END, w.depth + 1
    FROM walk w
    JOIN edges e ON e.src = w.node_id OR e.dst = w.node_id
    WHERE w.depth < $2
)
SELECT n.id, n.kind, n.weight
FROM nodes n
JOIN (SELECT DISTINCT node_id FROM walk) w ON n.id = w.node_id
ORDER BY n.weight DESC
LIMIT $3;
```

### 10.3 Keeping the database off the stall path

The memory store is on the critical path of every turn; the venue network is not trustworthy. Three rules:

1. **Mirror.** At startup `GraphService` loads every node (including embeddings) and edge for the profile into memory. `snapshot()`, `people()` and `node_count()` always read the mirror.
2. **Timed reads with fallback.** `vector_search` and `expand` run in SQL with `query_timeout_s`. On timeout or error, the same operation runs against the mirror in numpy, the call is logged, and `sys.status.memory_store` becomes `"mirror"` until a query succeeds again.
3. **Outbox writes.** Every write is applied to the mirror first, then sent to Postgres with `write_timeout_s`. A failed write goes to an in-process outbox, retried every `outbox_retry_s`, in order. The turn never waits for the retry.

If the database is unreachable at boot, the mirror is built from the fixture (§14) and `memory_store` is `"fixture"`.

Two asyncpg pools share the one database: `memory` (small, critical) and `telemetry` (best-effort, §18.3). A saturated telemetry pool can never starve memory reads.

---

## 11. Retrieval

Four stages, under 150 ms total.

1. **Seed.** Embed the query (partner utterance for round one; utterance + chosen intent for round two). pgvector nearest neighbours (§10.2). Top `vector_top_k` (25).
2. **Expand.** Two-hop traversal from seeds, union with seeds, truncate to `candidate_cap` (60) preferring higher weight.
3. **Partner boost.** If a partner is identified, unconditionally add that `Person` node and everything within one hop. **This is what makes the same intent produce a different sentence depending on who is listening**, and it is the most persuasive behaviour in the demo.
4. **Submodular selection.** Greedy facility-location maximisation over the candidate embeddings, `select_k` (8), implemented in numpy (SW-5).

Plain top-K returns eight near-duplicates. Facility location maximises coverage, so you get the dog's name *and* its dietary needs *and* the walking routine, rather than five memories of the same walk.

```python
class RetrievalResult(BaseModel):
    nodes: list[NodeRef]              # the 8 selected
    edges: list[EdgeRef]
    context_text: str
    activated_node_ids: list[str]     # everything traversed
```

`activated_node_ids` is deliberately larger than `nodes`: the dashboard pulses everything traversed, then brightens the eight selected.

Context is rendered one fact per line:

```
- Sofia is your daughter. You call her "mija".
- Sofia visits on Sunday afternoons.
- You dislike the recliner; it hurts your back.
- Rosie is your dog, a nine-year-old beagle.
```

Measure the four stages against Tiger Cloud from the venue at checkpoint 1. If stages 1–2 exceed 100 ms combined, serve them from the mirror (§10.3) and keep SQL for writes and analytics.

---

## 12. Generation

All calls go through `LLMProvider.complete(system, user, json_mode=...)` with a 6 s timeout and one retry on malformed JSON using a repair prompt. Second failure falls to the static provider.

### 12.1 Intent labels

```
You write short intent labels for a speech device used by someone who cannot speak.

They will choose ONE label. The label is not the sentence they will say — it is
the DIRECTION their reply will take.

Rules:
- Exactly {n_intents} labels.
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

Rendered on tiles 0–2. The last tile is always "Cancel", never LLM-generated. With three labels, the "at minimum" range rule uses all three.

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

The three candidates go on tiles 0–2 with Cancel on tile 3. `grounding` drives the node-highlight animation. Ids not present in the supplied facts are dropped silently rather than failing the turn.

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

Every committed change — create, reinforce, dedup merge — is written to `memory_events` with the `turn_id` and confidence. New nodes broadcast as `graph.bloom` and animate into place.

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
        │     │ INTENT_GEN   │  LLM → 3 labels + Cancel
        │     ├──────▼───────┤
        │     │ INTENT_WAIT  │  sequential slots, awaiting Selection
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
        │     │  LEARNING    │  reinforce + extract + memory_events + bloom
        └─────┴──────────────┘
```

**Timeouts.** `INTENT_WAIT` and `CANDIDATE_WAIT` end when P2 reports `max_cycles` complete with no selection, or after 40 s, whichever is first, and return to `IDLE` with a "No selection — listening again" message. Generation states expire at `generation.timeout_s` and fall through their provider chains.

**Speller mode** replaces `INTENT_GEN`/`INTENT_WAIT` with row/column scanning over `speller.py`'s grid, appending one character per selection, exiting to `SPEAKING` on the SPEAK cell.

**Concurrency rule.** The orchestrator drops any `Selection` arriving outside a `*_WAIT` state, and stamps every `show_targets` with a fresh `trial_id`. A selection whose `trial_id` does not match the current one is discarded. Without this you get stale-suggestion races.

**Recording.** At the end of `LEARNING`, one `conversation_turns` row is emitted (§18.2) with the utterance, labels, chosen intent, candidates, spoken sentence and grounding.

---

## 14. Onboarding

Served at `/` when `GET /api/onboarding/status` reports `seeded: false`.

`BioWizard.tsx` shows one large textarea pre-filled with the fixture persona, so a full seed is one click on stage. The user, or someone on their behalf, can edit or replace it and share as much or as little as they choose. A "shared by" field records who provided it.

`POST /api/onboarding/seed`:

1. Upsert the `profiles` row with the bio and `shared_by`
2. LLM call → JSON graph of nodes and edges. First pass asks for 40–60 nodes across a balanced spread of kinds; a second expansion call enriches each Person and Activity with related Things, Places and Memories. Target 150–300 nodes.
3. Validate against the pydantic seed schema; drop malformed entries rather than failing
4. Embed every node's display text
5. Insert into Tiger in one transaction, with one `memory_events` row per node (`action: 'seed'`)
6. **Stream `graph.bloom` in batches of ~10 nodes at 150 ms intervals**, so the dashboard shows the memory *growing* rather than appearing

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
│ StatusBar: ● LIVE  165.0 Hz / 0 drops  BAT 82%  LLM ● STT ● TTS ● DB ● [BADGE] │
├──────────────────────────────┬─────────────────────────────────────┤
│                              │  Transcript                          │
│   MemoryBrain (3D)           ├─────────────────────────────────────┤
│   3d-force-graph             │  SlotPanel                           │
│   ~60% of viewport           │  [ Yes please ][▶Not now ][ Ask… ][✕]│
│                              │  push ▓▓▓▓▓▓░░ 0.62 ─┊ hold ●●○○     │
│   pulse on retrieval         │  EMG  ░░░░░░░░ quiet                 │
│   glow when selected         ├─────────────────────────────────────┤
│   bloom when learned         │  HeadsetQuality (14 sensors, O1/O2 ★)│
├──────────────────────────────┴─────────────────────────────────────┤
│  BandPowerPlot — O1/O2 alpha and low-beta, 20 s scrolling, slots shaded │
├────────────────────────────────────────────────────────────────────┤
│  CandidatePanel — 3 sentences, chosen one enlarges and speaks        │
├──────────────────┬──────────────────┬──────────────┬───────────────┤
│ SessionAnalytics │ MemoryTimeline   │ PrivacyPanel │ SpectatorQR   │
└──────────────────┴──────────────────┴──────────────┴───────────────┘
```

The bottom row collapses to a tabbed strip on narrow viewports. Those four panels are independently removable; nothing else references them.

### 16.2 Component rules

**`MemoryBrain.tsx`** wraps `3d-force-graph` imperatively via a ref, outside React's render cycle. React state changes must never re-instantiate the graph; use the library's `graphData()` mutation API. Node size maps to weight, colour to kind. Three animations:

- *pulse* — `graph.activate`, travelling highlight along traversed edges, 600 ms
- *glow* — grounding nodes, sustained emissive 3 s then decay
- *bloom* — `graph.bloom`, node scales 0→full over 500 ms with edges drawing in

**`SlotPanel.tsx`** mirrors the stimulus: the four labels with the active slot highlighted in step with `stim.slot`. In `scan_switch` it shows the trigger power as a bar with the threshold as a vertical line and hold progress as pips. In `seq_flicker` it shows one z-score bar per tile with the threshold line. **This is the panel that proves the idle state is real** — judges watch the bar sit below the line until the pilot acts.

**`MuscleStrip.tsx`** shows `facial_power` continuously under the trigger bar and turns amber whenever it crosses `contamination_threshold` (DEMO-6). A contaminated selection is marked on the strip and in the transcript.

**`BandPowerPlot.tsx`** uses **uPlot**, mounted via ref, updated with `setData()`, with slot intervals shaded so a judge can see low-beta rise when the attended tile flickers. **`HeadsetQuality.tsx`** shows per-sensor contact quality on a head outline, O1/O2 emphasised.

**`StatusBar.tsx`** renders provider and database health, battery, stimulus integrity, and `sys.status.input_badge` in high contrast whenever non-null (§7.8).

### 16.3 WebSocket client

Single connection, exponential-backoff reconnect (250 ms → 4 s cap), typed discriminated union on `type`. On reconnect, request a fresh `graph.snapshot`.

**High-rate streams bypass React state entirely.** `eeg.bandpower`, `bci.command` and `bci.slot_scores` write into refs consumed by the plot components' animation frames.

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

The last link in every chain is local, offline and never fails. That is what makes SW-13 real: the backend boots and serves a complete turn with no API keys.

---
## 18. Tiger Data — one database for memory, conversations and signals

### 18.1 What lives where

| Data | Table | Kind |
|---|---|---|
| Who the user is, what was shared, by whom | `profiles` | relational |
| The memory graph | `nodes`, `edges` | relational + pgvector (§10) |
| Every conversation turn | `conversation_turns` | hypertable |
| Everything the memory learned, and when | `memory_events` | hypertable |
| Emotiv band power, 14 sensors × 5 bands at 8 Hz | `band_power` | hypertable, compressed |
| Mental-command and facial streams | `commands` | hypertable, compressed |
| Per-slot scores | `slot_scores` | hypertable |
| Every selection, with cued answer when known | `selections` | hypertable |
| Stimulus frame integrity | `stimulus_integrity` | hypertable |

This is the "relational profiles and high-frequency metric streams side by side" case: a query can join what the user said, what the system knew at that moment, and how clean the signal was, in one SQL statement.

### 18.2 Schema

`migrations/002_timeseries.sql`:

```sql
CREATE TABLE conversation_turns (
  ts TIMESTAMPTZ NOT NULL, profile_id TEXT NOT NULL, session_id TEXT NOT NULL,
  turn_id TEXT NOT NULL, partner_id TEXT, utterance TEXT,
  intents TEXT[], intent TEXT, candidates TEXT[], spoken_text TEXT,
  grounding TEXT[], llm_provider TEXT, tts_tier TEXT,
  total_latency_ms INTEGER, turn_usd NUMERIC(10,6));
SELECT create_hypertable('conversation_turns', 'ts', chunk_time_interval => INTERVAL '1 day');

CREATE TABLE memory_events (
  ts TIMESTAMPTZ NOT NULL, profile_id TEXT NOT NULL, turn_id TEXT,
  node_id TEXT, edge_id TEXT,
  action TEXT NOT NULL CHECK (action IN
    ('seed','create','reinforce','dedup_merge','purge')),
  confidence REAL, weight_after REAL, summary TEXT);
SELECT create_hypertable('memory_events', 'ts', chunk_time_interval => INTERVAL '1 day');

-- Narrow by sensor: 112 rows/s. Queries read one or two sensors far more
-- often than all fourteen, and compression segments by sensor.
CREATE TABLE band_power (
  ts TIMESTAMPTZ NOT NULL, session_id TEXT NOT NULL, sensor TEXT NOT NULL,
  theta REAL, alpha REAL, beta_l REAL, beta_h REAL, gamma REAL);
SELECT create_hypertable('band_power', 'ts', chunk_time_interval => INTERVAL '5 minutes');

CREATE TABLE commands (
  ts TIMESTAMPTZ NOT NULL, session_id TEXT NOT NULL,
  stream TEXT NOT NULL CHECK (stream IN ('com','fac')),
  action TEXT NOT NULL, power REAL NOT NULL);
SELECT create_hypertable('commands', 'ts', chunk_time_interval => INTERVAL '5 minutes');

CREATE TABLE slot_scores (
  ts TIMESTAMPTZ NOT NULL, session_id TEXT NOT NULL, trial_id TEXT NOT NULL,
  algorithm TEXT NOT NULL, cycle SMALLINT NOT NULL, target_idx SMALLINT NOT NULL,
  score REAL);
SELECT create_hypertable('slot_scores', 'ts', chunk_time_interval => INTERVAL '1 hour');

CREATE TABLE selections (
  ts TIMESTAMPTZ NOT NULL, session_id TEXT NOT NULL, trial_id TEXT NOT NULL,
  round TEXT NOT NULL, target_idx SMALLINT NOT NULL, label TEXT,
  confidence REAL, source TEXT, algorithm TEXT, trigger TEXT,
  contaminated BOOLEAN NOT NULL DEFAULT false,
  cued_idx SMALLINT, latency_s REAL);
SELECT create_hypertable('selections', 'ts', chunk_time_interval => INTERVAL '1 hour');

CREATE TABLE stimulus_integrity (
  ts TIMESTAMPTZ NOT NULL, session_id TEXT NOT NULL,
  measured_refresh_hz REAL NOT NULL, dropped_frames SMALLINT NOT NULL,
  interval_std_ms REAL);
SELECT create_hypertable('stimulus_integrity', 'ts', chunk_time_interval => INTERVAL '1 hour');

-- Continuous aggregates: the dashboard reads these, never the raw tables.
CREATE MATERIALIZED VIEW occipital_1s WITH (timescaledb.continuous) AS
SELECT time_bucket('1 second', ts) AS bucket, session_id, sensor,
       avg(alpha) AS alpha, avg(beta_l) AS beta_l
FROM band_power WHERE sensor IN ('O1','O2')
GROUP BY bucket, session_id, sensor;

CREATE MATERIALIZED VIEW accuracy_1m WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', ts) AS bucket, session_id, algorithm,
       count(*) AS n,
       count(*) FILTER (WHERE cued_idx = target_idx) AS n_correct,
       count(*) FILTER (WHERE contaminated) AS n_contaminated,
       avg(latency_s) AS mean_latency_s
FROM selections WHERE cued_idx IS NOT NULL
GROUP BY bucket, session_id, algorithm;

CREATE MATERIALIZED VIEW learning_10m WITH (timescaledb.continuous) AS
SELECT time_bucket('10 minutes', ts) AS bucket, profile_id, action,
       count(*) AS n, avg(confidence) AS mean_confidence
FROM memory_events GROUP BY bucket, profile_id, action;

SELECT add_continuous_aggregate_policy('occipital_1s',
  start_offset => INTERVAL '10 minutes', end_offset => INTERVAL '1 second',
  schedule_interval => INTERVAL '2 seconds');
SELECT add_continuous_aggregate_policy('accuracy_1m',
  start_offset => INTERVAL '1 day', end_offset => INTERVAL '1 minute',
  schedule_interval => INTERVAL '30 seconds');
SELECT add_continuous_aggregate_policy('learning_10m',
  start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute');

ALTER TABLE band_power SET (timescaledb.compress,
  timescaledb.compress_segmentby = 'session_id, sensor');
SELECT add_compression_policy('band_power', INTERVAL '10 minutes');
ALTER TABLE commands SET (timescaledb.compress,
  timescaledb.compress_segmentby = 'session_id, stream');
SELECT add_compression_policy('commands', INTERVAL '10 minutes');
```

Before the pitch, run `SELECT * FROM hypertable_compression_stats('band_power')` and quote the measured ratio, not the marketing one.

### 18.3 The rule that matters

**Telemetry must never be able to stall the pipeline.**

`telemetry.py` exposes a synchronous `emit(record)` that does exactly one thing: `queue.put_nowait`. On `QueueFull` it increments a dropped counter and returns. It never awaits, never retries, never raises.

A consumer task drains every `flush_interval_ms`, batches up to `flush_batch` rows per table, and writes via `asyncpg` `copy_records_to_table` on the **telemetry** pool. If the database is unreachable, the consumer logs once per 30 s and keeps draining into the void so the queue never backs up.

`conversation_turns` and `memory_events` are **not** telemetry: they are written through the memory path (§10.3) with the outbox, because losing them loses the user's history.

`tests/test_telemetry.py` asserts that with the consumer stalled, 10,000 `emit()` calls complete in under 50 ms and the dropped counter equals the overflow. Dropped count surfaces in `sys.status`; if non-zero, raise `bandpower_downsample` to 2.

### 18.4 Analytics panel

`SessionAnalytics.tsx`, fed by `analytics.summary` every 2 s from the continuous aggregates.

**Always available:**

- **Occipital alpha and low-beta**, from `occipital_1s`, with selections overlaid
- **Selection latency distribution** and **selections per minute**
- **Contaminated fraction** of mental-command selections
- **Frame integrity strip**

**Requires cued trials** (§18.6):

- **Accuracy over time**, per method, from `accuracy_1m`
- **Information Transfer Rate** in bits/min, from accuracy, target count and mean selection time

`accuracy_pct` and `itr_bits_per_min` are **nullable**. When `cued_trials == 0` the panel renders those tiles greyed with "run a cued block to measure", not an empty chart. This panel is the honest answer to "how do you know it's working?" It must not display a number it cannot compute.

### 18.5 Memory timeline

`MemoryTimeline.tsx`, fed by `GET /api/memory/timeline` and `learning_10m`: a scrolling list of what the system learned, from which conversation, with what confidence — "Learned: *needs an adjustable chair* (0.82), from Sofia, 14:32". It makes the continuously-updating profile visible and auditable, and it is a query no graph-only database answers in one statement:

```sql
SELECT m.ts, m.action, n.kind, coalesce(n.name, n.text) AS fact,
       m.confidence, t.partner_id, t.utterance
FROM memory_events m
JOIN nodes n ON n.id = m.node_id
LEFT JOIN conversation_turns t ON t.turn_id = m.turn_id
WHERE m.profile_id = $1 AND m.ts > $2
ORDER BY m.ts DESC LIMIT 50;
```

### 18.6 Cued blocks

A cued block is a short run where the stimulus outlines the tile to choose, so the correct answer is recorded alongside the selection. It is the only source of `selections.cued_idx`, and therefore of accuracy and ITR.

`POST /api/cued_block/start {n_trials: int = 20}`:

1. For each trial, pick a target at random, publish `stim.show_targets` with `cue_idx` set
2. The stimulus outlines that tile during the cue phase
3. Record the resulting selection with `cued_idx` populated

`scripts/feasibility.py` (§7.6) is a cued block per method plus the statistics. Run one during pre-judging setup: it populates the panel and gives the presenter a real figure to quote.

---

## 19. Spectator relay

A judge three metres away cannot read the dashboard. A QR code on the pilot's table opens a phone-sized live view: which tile is active, the transcript, the sentence just spoken, a memory-node counter.

```
PC ──outbound WS──► DO droplet ──WS──► judge phones
     (producer)      relay.py          static/index.html
```

**Outbound only.** The PC dials the relay; the relay never dials in, never sends commands, and nothing arriving from it enters the pipeline. `spectator.py` is a write-only client.

$6/mo basic droplet, Docker, Caddy for TLS, domain from GoDaddy Registry.

| Sent | Not sent |
|---|---|
| Active tile and selected label, 1 Hz | Band power or command streams |
| Partner utterance transcript | Personal memory node text |
| Spoken sentences | Node/edge contents, embeddings |
| Node and edge **counts** by kind | The persona's private details |
| Refresh rate, dropped frames | Keys, internal identifiers |

**Gradient AI** serves an OpenAI-compatible endpoint, so it slots into `llm_openai_compat.py` with no new code — only three env vars. It sits third in the LLM chain.

---

## 20. Data and privacy

This system builds a structured model of a disabled person's family, home, needs and routine, stores every conversation, and sends fragments to cloud vendors on every turn. That is the correct trade for capability, and it is exactly the situation where a user deserves to see what is happening and be able to stop it.

**Consent at onboarding.** The wizard states what is stored (the profile, every conversation, the memory built from them, the headset's band-power and command streams) and where (Tiger Cloud). `shared_by` records who provided the bio.

**Data flow ledger.** Every outbound call emits `privacy.flow`. The panel renders, for example:

```
This session, data has left this machine 31 times:

  → Gemini (Google)      9 calls   intent labels, sentences, fact extraction
                                   sends: partner utterance + 8 retrieved facts
  → ElevenLabs           4 calls   speech synthesis — the sentence text only
  → Deepgram             1 call    transcription — 3.2 s of microphone audio
  → Tiger Cloud         17 writes  your memory, conversations, headset streams
  → Spectator relay    312 events  selections + spoken lines. No memory content.

Never sent to an AI vendor: your full memory, headset streams, voice enrollment audio
```

**Cost visibility.** `cost.py` accumulates tokens, characters and audio seconds per turn, multiplies by `privacy.price_table`, emits `privacy.cost`, and stores `turn_usd` in `conversation_turns`.

**Local Mode.** One toggle. LLM truncates to a local endpoint then static; STT to `faster_whisper`; TTS to cache then Piper (no voice clone — **say this plainly in the UI**); memory served from the mirror with writes held in the outbox; spectator disconnects; telemetry uploads pause. A `LOCAL MODE` badge appears. No restart.

**Purge.** `POST /api/privacy/purge` with scope `memory` deletes the profile's nodes and edges (cascade) and logs a `purge` event; `conversations` deletes `conversation_turns` and `memory_events` for the profile; `signals` deletes the session's `band_power`, `commands`, `slot_scores` and `selections`; `all` does all three plus clears the audio cache. Confirmation required.

---

## 21. Build plan

### 21.1 Roles

| | Scope |
|---|---|
| **Dev A** | Contract changes (§6) and config (§5) per AGENTS.md §4, `inputs/bci.py` rename, orchestrator for four sequential targets, `db.py` pools, integration. |
| **Dev B** | P1 end to end (Cortex bridge, training, both decision methods, synthetic, recorder) and P2 (sequential stimulus). One person owns both halves of the loop. Runs the feasibility gate. |
| **Dev C** | Frontend: SlotPanel, MuscleStrip, BandPowerPlot, HeadsetQuality, MemoryTimeline, plus the existing panel set. |
| **Dev D** | Port `graph.py` from Kuzu to Tiger (§10), migrations, `memory_events` from onboarding and extraction, `conversation_turns`, retrieval latency against Tiger Cloud. |

Pilot: whoever wears the headset trains the mental command and does not present. Presenter: Dev D.

### 21.2 Remaining work, from revision 2

Hours are counted from when this revision lands (H+0).

| Hours | Dev A | Dev B | Dev C | Dev D |
|---|---|---|---|---|
| **0–2** | Schemas §6 + `types.ts`, config §5 — one contract commit | `check_cortex.py`: licence-free streams arrive, contact quality green. `check_stimulus.py` at 165 Hz | Scaffold Vite app from the prototype; SlotPanel against `fake_sensor.py` | Tiger Cloud service, `001_memory.sql`, `002_timeseries.sql` applied |
| **2–6** | `inputs/bci.py`, orchestrator four-target flow, `db.py` | `sources/cortex.py`, `sources/synthetic.py`, `decision/scan_switch.py` | MuscleStrip, BandPowerPlot, HeadsetQuality | `graph.py` on asyncpg + mirror + outbox; existing graph tests passing against local Postgres |
| **6–8** | **FEASIBILITY GATE (§7.6).** Train `push`, run the cued blocks, record the numbers in `CHANGELOG.md`, pick the method. | | | |
| **8–14** | Wire telemetry to the new tables | P2 sequential stimulus, `decision/seq_flicker.py`, recorder, replay | MemoryBrain, CandidatePanel, Transcript on the real WS | `memory_events` from onboarding + extraction, `conversation_turns`, timeline endpoint |
| **14–16** | **CHECKPOINT 1.** Headset, real LLM, real voice, Tiger, full turn end to end. | | | |
| **16–22** | Gemini/ElevenLabs verification, cost, Local Mode | Speller scan grid; retrain if accuracy drifted | SessionAnalytics, MemoryTimeline, PrivacyPanel | Retrieval latency from venue; compression ratio; pitch script |
| **22–24** | **FEATURE FREEZE.** `prerender_cache.py`. Backup video. Clean replay session. Cued block for the analytics panel. | | | |

### 21.3 Critical path

Contract commit (H+2) → `sources/cortex.py` + `scan_switch.py` (H+6) → feasibility gate (H+8) → checkpoint 1 (H+16).

`graph.py` on Tiger is the second critical path: until it lands, the rest of the pipeline keeps running on the Kuzu implementation, so it does not block anyone else.

### 21.4 Cut order

1. `seq_flicker` (keep `scan_switch`)
2. Speller
3. Spectator relay (forfeits DigitalOcean; keep the Gradient provider)
4. Privacy panel and Local Mode (forfeits Assurant)
5. MemoryTimeline panel (keep `memory_events` — the table is the Tiger story)
6. Fact extraction writeback (keep edge reinforcement)
7. Partner identification (hardcode one partner)
8. Onboarding wizard (load the fixture)

**Never cut:** the idle state, the muscle strip, the memory brain, the voice clone, and Tiger as the memory store. Those five are the demo.

---

## 22. Failure modes

| Failure | Detection | Response |
|---|---|---|
| EMOTIV Launcher / Cortex not running | `check_cortex.py`, P1 startup | Start the Launcher, log in. P1 falls back to synthetic with the badge. |
| Cortex rejects a stream | `subscribe` error | Confirm only licence-free streams are requested (§8.1); raw `eeg` is never requested. |
| Poor contact | `dev` below `min_contact_quality` | Rehydrate the sensors, reseat O1/O2. Do not run a cued block until green. |
| Headset battery low | `battery_pct` | Charge between sessions; a USB-charging headset is still wireless while recording. |
| Mental command never reaches threshold | `hold_count` never reaches 4 | Retrain (§8.2); lower `power_threshold` to 0.35 |
| Mental command fires at rest | Selections with no intent | Retrain neutral; raise `power_threshold`; raise `hold_s` to 0.75 |
| Trigger is really the jaw | High contaminated fraction | Retrain with "face slack"; if it persists, switch to `trigger: facial` openly with its badge |
| `seq_flicker` never clears margin | Winner z < threshold | Check O1/O2 contact; raise contrast; accept that it is the pure-EEG mode and may be cut |
| Panel silently at 60 Hz | `stim.profile.measured_refresh_hz` | Check power profile, cable, GPU assignment. 15 Hz stays exact; carry on and log. |
| Frame drops > threshold | `stim.integrity` | Close other GPU-heavy apps; sustained > 10 s shows a dashboard warning |
| Tiger Cloud slow or unreachable | Query timeout | Mirror serves reads, outbox holds writes, `memory_store: mirror`. The turn completes. |
| Telemetry queue saturating | Non-zero drop counter | Raise `bandpower_downsample`. **Never raise `queue_maxsize`.** |
| LLM timeout | 6 s elapsed | Chain to the next provider, then static. The turn always completes. |
| STT garbage | Confidence < 0.5 or < 2 words | Discard; stay IDLE. Operator can use `POST /api/utterance`. |
| ElevenLabs down | HTTP error | Cache → Piper → browser. Never silent. |
| Duplicate node explosion | `node_count` growing > 4/turn | Lower `dedup_similarity` from 0.88 to 0.82 |
| System transcribes itself | Self-talk loop | Mic hard-gate during SPEAKING — verify at checkpoint 1 |
| **Total live demo failure** | — | Switch to `replay`. Say plainly that this is a session recorded earlier. If that fails, the backup video. |

---

## 23. Acceptance tests

Go/no-go gates, in order.

| # | Test | Pass criterion |
|---|---|---|
| A1 | `check_stimulus.py` on the PC, 30 s | Measured refresh within 0.5 Hz of 165, `exact: true`, zero dropped frames, interval σ < 0.5 ms |
| A2 | `check_cortex.py` | `pow`, `com`, `fac`, `dev`, `eq` all arriving at their rates; O1/O2 contact ≥ 3 |
| A3 | `pytest tests/test_scan_switch.py tests/test_seq_flicker.py` | ≥95% correct attribution on synthetic; ≤2% selections with no intent; contamination flag set when fac overlaps |
| A4 | `pytest tests/test_telemetry.py` | 10,000 `emit()` with a stalled consumer complete in <50 ms; nothing raises |
| A5 | **Keyboard end-to-end** | With `input.adapter: keyboard` and no headset, a full turn completes: utterance → intents → selection → candidates → selection → audio → bloom → `memory_events` row |
| A6 | **Offline boot** | With an empty `.env`, the backend starts on the fixture mirror and a full turn completes on fallback providers |
| A7 | Idle state | Headset on, pilot relaxed and looking at the tiles for 60 s, zero selections |
| A8 | **Feasibility gate** | `scan_switch` ≥ 80% over 20 cued trials, p < 0.05, contaminated < 20%. `seq_flicker` recorded, pass mark 60%. |
| A9 | Latency | Selection → first audio ≤ 2.5 s uncached, ≤ 300 ms cached |
| A10 | Partner conditioning | Same utterance and intent, two partners, two audibly different sentences with the right term of address |
| A11 | Writeback | A novel fact mentioned in conversation appears as a node within one turn, is retrievable in the next, and shows in the memory timeline |
| A12 | Database outage | Block Tiger Cloud mid-session: the next turn completes from the mirror; unblock, and the outbox drains with no lost `memory_events` |
| A13 | Recovery | Kill the backend mid-turn; restart; dashboard reconnects, memory intact |
| A14 | Replay | A recorded session replays through the real decision logic and reproduces the same selections, badge visible |
| A15 | Analytics | After 20 cued trials the panel shows a non-empty accuracy series and the contaminated fraction |
| A16 | Compression | `hypertable_compression_stats('band_power')` reports a measured ratio after 10 minutes of recording |
| A17 | Spectator | A phone on cellular data loads the domain and shows selections within 2 s; payloads contain no signal streams, memory text or keys |
| A18 | Local Mode, network physically off | Full turn completes in the Piper voice, memory updated in the mirror, outbox drains when the network returns |
| A19 | Purge | `purge {scope:"all"}` empties memory, conversations and signals; dashboard returns to onboarding |

---

## 24. Assumptions

| # | Item | Default |
|---|---|---|
| 1 | Headset | Emotiv EPOC X, free Cortex licence, EMOTIV Launcher installed and logged in on the PC |
| 2 | Cortex app credentials | A Cortex app registered on the Emotiv developer site; id and secret in `.env` |
| 3 | Display | The PC's built-in 165 Hz panel for the stimulus; dashboard on an external display if one exists |
| 4 | Pilot training | ~10 minutes of neutral + push training before the feasibility gate, repeated if accuracy drifts |
| 5 | Tiger Cloud free tier | Sufficient for the memory store and a weekend of compressed band power |
| 6 | Deepgram key | Free tier. If unavailable, `faster-whisper small` on CPU adds ~1.5 s per utterance |
| 7 | Presenter | Dev D; the pilot does not present |
| 8 | Persona | Marcus Alvarez, editable at runtime |
| 9 | Voice enrollment | The pilot, 60 s, recorded before the event, with consent |
| 10 | OpenBCI | Not available unless stated; §8.7 is contingency only |

---

## 25. Credits and prior art

To be reproduced in `CREDITS.md` and referenced in the Devpost submission.

- **Lucid Voice** (UC Berkeley AI Hackathon 2026) — prior art. Its public README was read for architectural patterns: provider abstraction, lazy graceful-degradation service construction, cache-first speech, three-candidate selection. No source code was copied.
- **Switch scanning with an attempted-movement click** — Candrea et al., *A click-based electrocorticographic brain-computer interface enables long-term high-performance switch scan spelling*, Communications Medicine 2024.
- **Motor imagery on the EPOC X** — *Motor imagery-based brain-computer interfaces: an exploration of multiclass motor imagery-based control for Emotiv EPOC X*, Frontiers in Neuroinformatics 2025 — the evidence behind §7.7.
- **SSVEP** — the visual-cortex frequency-following response that `seq_flicker` measures.
- **Facility location submodular selection** — Schreiber et al., `apricot`, JMLR 2020 (algorithm; implemented directly in numpy here).
- Libraries: Emotiv Cortex API, PsychoPy, NumPy, SciPy, asyncpg, pgvector, TimescaleDB, sentence-transformers, FastAPI, uvicorn, pydantic, PyZMQ, React, Vite, Tailwind, 3d-force-graph, three.js, uPlot, webrtcvad, sounddevice, Piper, faster-whisper, qrcode.
- Services: Emotiv, Google Gemini, ElevenLabs, Deepgram, Tiger Data, DigitalOcean, GoDaddy Registry.

---

## 26. Submission notes

The Devpost writeup needs **one distinct paragraph per track**, naming the specific component. A judge skimming for their own technology should find it in five seconds.

| Track | The paragraph is about | Point at |
|---|---|---|
| **Microsoft** | Communication for people with motor neuron disease runs at ~8 wpm against speech's 150. We replaced character spelling with semantic intent selection by brain switch. **The product has no chat window** — the interface is a scanning tile row and a 3D memory graph. | §1, §13 |
| **Tiger Data** | One PostgreSQL holds everything: the user's profile and memory graph (relational + pgvector similarity search + recursive-CTE graph walks), every conversation, a `memory_events` hypertable recording what the system learned and when, and 8 Hz × 14-sensor band power beside every selection. Continuous aggregates drive live accuracy, signal and learning panels; compression keeps the headset streams on the free tier (quote the measured ratio). The memory path has a mirror and outbox so a database hiccup never silences the user; telemetry is a drop-on-overflow queue. | §10, §18 |
| **ElevenLabs** | The user's own voice, cloned from a 60 s clip, restored as the output of a brain-driven pipeline. Cache-first playback so the demo is network-independent. | §15.2 |
| **Gemini** | Four call sites — intent labels, grounded sentences, partner identification, post-turn fact extraction that grows the memory — under strict-JSON contracts with repair retry and a fallback chain. | §12 |
| **DigitalOcean** | Droplet-hosted spectator relay; judges watch on their phones via a write-only sanitised stream. Gradient AI is the third LLM link. | §19 |
| **GoDaddy** | Domain fronting the spectator view. | §19 |
| **Assurant** | A system holding a disabled person's life should show what leaves the machine. Live data-flow ledger, per-turn cost, scoped purge, and a Local Mode demonstrated on stage. | §20 |

**Do not claim a track whose component was cut**, and quote only accuracy numbers measured by the feasibility gate and cued blocks.

---

## 27. Change history

Every change to this document is recorded in `CHANGELOG.md` with its date, the sections touched, why, and the code follow-ups it creates. Update it in the same commit as the change.
