# CHANGELOG

Changes to `ARCHITECTURE.md`, newest first. Each entry lists what changed, why, and the code follow-ups it creates. Update this file in the same commit as the architecture change.

---

## Revision 2.1 — 2026-09-27

**Author:** Zahid (with Claude). **Why:** first feasibility test for `seq_flicker` (Option 2), and a timing fact confirmed in the Cortex API docs: each `pow` sample is computed from the **last 2 seconds** of EEG, at 8 Hz, in uV²/Hz.

| § | Change |
|---|---|
| 4 | Added `experiments/seq_flicker/` to the layout. |
| 5 | `stimulus.seq_flicker.slot_s` 3.0 → **4.0**, `gap_s` 0.5 → **1.0**; `decision.seq_flicker.score_tail_s` 1.5 → **2.0**. A 3 s slot left only ~1 s of samples whose 2 s window lies inside the slot. |
| 7.3 | `seq_flicker` time per pass updated (≈20 s for four slots). |
| 7.6 | Points to the standalone test tool and its plan; three-tile chance level stated. |
| 8.4 | States the 2 s window as fact, and that scoring uses log power. |

**Added (code, outside all owned paths):** `experiments/seq_flicker/` — `run_test.py` (fullscreen stimulus with START button, vsync-locked, frame-drop counting), `cortex_client.py` (free-tier streams only), `recorder.py`, `analyze.py` (primary analysis fixed in advance + controls + exploratory), `synthetic.py` (dry runs), `TEST_PLAN.md`, `README.md`, `requirements.txt`, `sessions/.gitignore`. Tested headless with synthetic data: an effect of 1 SD scores 67% (p = 0.0002) and no effect scores 27% (chance). The on-screen flow was checked on a virtual display. **Not yet run on the real headset or at 165 Hz.**

**Design changes from the proposed protocol** (reasons in `TEST_PLAN.md` §2): 4 s slots + 1 s gaps; 10 cycles per run (30 decisions; 15 correct needed for p < 0.05); order shuffled within each cycle but identical across runs; 30 s baseline; three-rep all-flicker signal check; a fourth look-at-the-cross control run; fixation dot; mean-luminance-matched flicker; photosensitivity warning.

### Fixes after the first run on the PC

- `run_test.py`: connects to Cortex **before** opening the window (the connection can block for a minute while the Launcher asks for approval, which froze the fullscreen window); refresh measurement is capped at 5 s; the console logs each step; `--windowed` option; an early close no longer crashes the analysis. README: `python -m pip` setup and a troubleshooting section.
- The window then measured ~2 frames/s on the laptop (the whole window flickered). Added `check_display.py` (fullscreen/windowed × vsync on/off, fps and OpenGL renderer), a `--no-vsync` option, time-based flicker so the frequency stays at 15 Hz even when frames drop, and a guard that refuses to start below 60 fps.

### Open items

- [x] **First headset session — 2026-09-27, subject `khan`, EPOC X, session `20260927-012345_khan_emotiv`.** Recording clean: contact 4/4 on all 14 sensors throughout, display 165.4 Hz (11.03 frames per 15 Hz cycle), 22 dropped frames in total, timestamps aligned (pow at 8.0 Hz covering every event).
  - Signal check **FAIL**: flicker on vs off in O1/O2 low-beta = −0.00 SD (reps +0.44, −0.56, +0.12). No sensor/band showed a consistent on/off difference across the three reps.
  - Primary: **13/30 = 43%** (chance 33%), p = 0.17 — not above chance. Confusion roughly flat; time course shows no rise for the looked-at tile.
  - Control run: idle rule would have selected in 4/10 cycles (target 0–1).
  - Side finding: O1/O2 gamma and beta rose 1–4 SD during runs 1–3, the same minutes Emotiv's facial stream reported lower-face activity (smirk/laugh) 25–42% of the time, vs 2–5% in baseline and signal check. Likely jaw/face muscle tension while holding gaze — broadband EMG that swamps any small 15 Hz response.
  - Reading: the analysis rule labels this INCONCLUSIVE because the signal check failed, but contact was perfect, so poor contact is ruled out. With a clean signal check period (low muscle activity) still showing no response, free-tier band power does not appear sensitive enough to see a 15 Hz flicker. **Treat `seq_flicker` as not viable on this path unless one decisive retest changes that.**
- [ ] If GO: repeat with runs in reverse order before building it into the demo.

---

## Revision 2 — 2026-09-27

**Author:** Zahid (with Claude). **Status:** Kuzu → Tiger Data agreed by the team. The hardware and selection-method changes follow from the equipment actually available and need the feasibility gate (§7.6) to confirm the final method.

**Base:** this revision was edited from the ARCHITECTURE.md shared in the Flick project, which is newer than the copy at repo HEAD (it contains §6.3 inbound client channel and §18.4 cued blocks, matching commits `73076fb` and `b60ef54`).

### Why

1. **Hardware.** The team is using an **Emotiv EPOC X on the free Cortex tier**, not an OpenBCI Cyton. The free tier provides band power (`pow`), mental commands (`com`), facial expressions (`fac`), device status (`dev`) and EEG quality (`eq`), but **not raw EEG**. FBCCA, eTRCA, the notch/bandpass chain and five simultaneous frequencies all require raw EEG, so they cannot run.
2. **Accuracy.** Band power cannot tell 8 Hz from 9.6 Hz (both are "alpha"). Presenting tiles one at a time removes the need to separate frequencies. A single trained command against rest is far easier to detect than four- or five-way classification.
3. **Database.** Tiger Data replaces KuzuDB so the user's profile, memory graph, conversations, learning history and headset streams live in one PostgreSQL. It is also a much stronger Tiger Data track entry.
4. **Machine.** The demo runs on one PC: 165 Hz panel, RTX 5050.

### What changed, by section

| § | Change |
|---|---|
| Header | Revision note added. |
| 1.1 | Four tiles (three intents + Cancel), presented sequentially; two selection methods; onboarding data + continuous profile updates stated. |
| 1.3 | Speller uses row/column scanning. |
| 1.4 | Non-goals: added simultaneous multi-frequency SSVEP (needs raw EEG) and a second machine. Removed "EMG hybrid confirmation" (a facial trigger is now an allowed, badged fallback). |
| 1.5 | Tiger Data raised from P1 to **P0**, described as the only database. |
| 2.1 | HW-1…HW-6 rewritten: Emotiv EPOC X free tier, streams available, sensors used, saline setup, one PC, OpenBCI contingency only. |
| 2.2 | UX-2 four targets / `n_intents` 3. UX-3 selection method `scan_switch` default, `seq_flicker` pure-EEG mode. UX-5 fixed flicker at 15.0 Hz (exact divisor of 165, 120, 60). Old UX-3 (profile-dependent frequencies) and UX-5 (dwell confirmation) removed. |
| 2.3 | DSP-1…DSP-6 rewritten: no raw-EEG processing; trigger hold rule; band-power z-score; Cortex training; ZMQ slot onsets replace LSL. |
| 2.4 | SW-3 Kuzu → Tiger Data (PostgreSQL + TimescaleDB + pgvector). SW-5 updated to numpy facility location (matches `retrieval.py`; apricot measured 800–900 ms). SW-9 notes the GPU exists but is not required. SW-10 adds `memory_events`. SW-14 rewritten: telemetry off the critical path, memory store on it but guarded by mirror + outbox. SW-16 Local Mode serves memory from the mirror. |
| 2.5 | DEMO-3 badges extended (`SYNTHETIC SIGNAL`, `MUSCLE TRIGGER (EMG)`). New DEMO-6 (muscle activity always visible, `contaminated` flag) and DEMO-7 (honest pitch language). |
| 3 | Single-machine topology; Tiger Cloud and Cortex added; P1 now subscribes to P2 (`5557`) for slot onsets; LSL outlet removed. Turn flow updated. |
| 4 | Layout: `inputs/ssvep.py` → `inputs/bci.py`; `inputs/emotiv.py` removed (Emotiv now enters through P1); `sensor/` rebuilt around `sources/cortex.py`, `decision/{scan_switch,seq_flicker}.py`, `training.py`; `dsp.py`, `classifiers/`, `calibration.py`, `stimulus/markers.py` removed; `backend/app/services/db.py` added; frontend components `EegTrace`, `PsdPlot`, `TargetScores` replaced by `BandPowerPlot`, `HeadsetQuality`, `SlotPanel`, `MuscleStrip`, `MemoryTimeline`; migrations split into `001_memory.sql` and `002_timeseries.sql`; new scripts `check_cortex.py`, `train_command.py`, `feasibility.py`, `seed_tiger.py`. `CHANGELOG.md` added. |
| 5 | Config rewritten: `mode.selection`, `mode.trigger`, `emotiv`, simplified `stimulus` (fixed 15 Hz, `scan` / `seq_flicker` blocks), `decision` per method, `calibration` for Cortex training, new `database` block, `graph.db_path` removed, `n_intents: 3`, telemetry `bandpower_downsample`, spectator `send_signal`. `.env`: `TIMESCALE_DSN` → `TIGER_DSN`, added `LOCAL_PG_DSN`. |
| 6.1 | `Selection`: `source` values now `bci` / `keyboard` / `replay`; `algorithm` now `scan_switch` / `seq_flicker`; new optional `trigger` and `contaminated`. |
| 6.2 | `EegChunk`, `PsdFrame`, `TargetScores` replaced by `BandPowerFrame`, `CommandFrame`, `SlotScores`. `SensorSelection` uses `score` instead of `rho` and adds `trigger`, `contaminated`. `SensorStatus` reports Emotiv battery, contact quality, profile and trained actions. |
| 6.3 | `KeyPress` keys "1".."4". |
| 6.4 | `ShowTargets` unchanged apart from Cancel last. `StimControl` actions `start` / `stop` / `confirm`. |
| 6.5 | `StimulusProfile` simplified to refresh + 15 Hz frames-per-cycle + slot timing. `StimulusOnset` replaced by `StimulusSlot` (`stim.slot`), now also consumed by P1. |
| 6.6 | WS: `eeg.trace` / `eeg.psd` → `eeg.bandpower`; added `bci.command`, `bci.slot_scores`, `stim.slot`; `sys.status` gains battery, contact quality, profile, `memory_store`; `analytics.summary` gains `contaminated_pct`, `facts_learned_last_10m`. |
| 6.7 | `label` rule now guaranteed by a table CHECK constraint. |
| 6.8 | REST: added `/api/selection_method`, `/api/training/start`, `/api/training/status`, `/api/memory/timeline`; `cued_block` loses `train_etrca`. |
| 7 | Rewritten: `bci` adapter; selection methods `scan_switch` and `seq_flicker`; feasibility gate with pass marks; two-command attempted movement moved to experimental with the evidence against it; badge rule updated. Old §7.5 Emotiv band-power/wink section folded in. |
| 8 | Rewritten as the Cortex bridge: connection sequence, streams, mental-command training protocol, `scan_switch` state machine with attribution and contamination, `seq_flicker` scoring, synthetic source for the new streams, JSONL recorder, OpenBCI contingency. FBCCA/eTRCA/filter chain removed. |
| 9 | Stimulus: fixed 15 Hz sinusoid, refresh check instead of hi/lo profiles, single-row layout, sequential trial sequence, cued outline. Harmonic-collision rule and LSL removed. |
| 10 | Kuzu schema replaced by PostgreSQL: `profiles`, `nodes` (JSONB attrs, `vector(384)`, HNSW index, kind CHECK), `edge_rules`, `edges`. Operations become async; pgvector search and recursive-CTE expansion given. New §10.3: mirror, timed reads with fallback, write outbox, two pools. |
| 11 | Seed stage uses pgvector; stage 4 documented as numpy facility location; latency check against Tiger Cloud from the venue. |
| 12 | Intent prompt takes `{n_intents}` (3). Candidates on tiles 0–2. Extraction writes `memory_events`. |
| 13 | FSM labels updated; wait-state timeout tied to `max_cycles` or 40 s; speller uses scanning; `conversation_turns` row per turn. |
| 14 | Onboarding writes `profiles` with `shared_by`; inserts into Tiger with `seed` events. |
| 15 | Unchanged. |
| 16 | Layout and component rules for the new panels. |
| 17 | Unchanged. |
| 18 | Rewritten as "Tiger Data — one database": table map, full hypertable schema (`conversation_turns`, `memory_events`, `band_power`, `commands`, `slot_scores`, `selections`, `stimulus_integrity`), continuous aggregates (`occipital_1s`, `accuracy_1m`, `learning_10m`), compression, telemetry rule, analytics panel, new memory timeline (§18.5), cued blocks (§18.6). |
| 19 | Spectator sends no signal streams; wording for one PC. |
| 20 | Consent at onboarding; Tiger Cloud in the ledger; Local Mode memory behaviour; purge scopes `memory` / `conversations` / `signals` / `all`. |
| 21 | Roles updated; schedule replaced by remaining work from this revision with a feasibility gate at H+6–8; new cut order and never-cut list. |
| 22 | Failure modes for Cortex, contact, battery, mental-command drift, muscle contamination, Tiger outage. OpenBCI-specific rows removed. |
| 23 | Acceptance tests renumbered: A2 Cortex check, A3 decision tests, A8 feasibility gate, A12 database outage, A16 compression. |
| 24 | Assumptions for Emotiv, Cortex credentials, one PC, Tiger free tier. |
| 25 | Credits: FBCCA, TRCA, Kuzu, BrainFlow, pylsl removed; switch-scan ECoG study, EPOC X motor-imagery study, Emotiv Cortex, pgvector, TimescaleDB added. |
| 26 | Tiger Data paragraph rewritten around the unified database. |
| 27 | New: pointer to this file. |

### Code follow-ups this revision creates

Contract changes go through AGENTS.md §4 (announce, confirm, one commit with `types.ts`).

- **`shared/schemas.py` + `frontend/src/lib/types.ts`** — §6.1, §6.2, §6.4, §6.5, §6.6 changes. One contract commit.
- **`config.yaml`, `shared/config.py`, `.env.example`** — §5.
- **`inputs/ssvep.py` → `inputs/bci.py`**, badge logic per §7.2; `tests/test_inputs.py`.
- **`backend/app/services/graph.py`** — port from Kuzu to asyncpg + pgvector with mirror and outbox (§10). `tests/test_graph.py`, `test_retrieval.py`, `test_extraction.py`, `test_onboarding.py`, `test_partner.py` currently build `GraphService(db_path=...)` and must move to a disposable Postgres (`LOCAL_PG_DSN`).
- **`backend/app/services/db.py`** — new; two pools.
- **`migrations/001_timescale.sql`** → `001_memory.sql` + `002_timeseries.sql`.
- **`backend/app/services/telemetry.py`**, **`analytics.py`** — new tables and aggregates.
- **`backend/app/services/extraction.py`**, **`onboarding.py`** — write `memory_events`.
- **`backend/app/orchestrator.py`** — four sequential targets, `conversation_turns`, new timeout rule.
- **`backend/prompts/intent_labels.txt`** — `{n_intents}`.
- **`pyproject.toml`** — remove `kuzu`; add `websockets` (Cortex client) and `pgvector` (asyncpg codec); `scipy` only if still used.
- **`sensor/`, `stimulus/`** — new, per §8 and §9.
- **`scripts/fake_sensor.py`** — emit the new `bci.*` messages.
- **`run.sh`** — unchanged process list; P1 needs the EMOTIV Launcher running first.
- **Frontend** — new components per §16.

### Open items

- [ ] Feasibility gate results (§7.6): `scan_switch` accuracy ___ %, contaminated ___ %; `seq_flicker` accuracy ___ %. Record here with date.
- [ ] Measured retrieval latency against Tiger Cloud from the venue (§11).
- [ ] Measured `band_power` compression ratio (A16).
- [ ] Commit ARCHITECTURE.md and CHANGELOG.md to git (written to the working tree; repo HEAD still holds revision 1).

---

## Revision 1 — before 2026-09-27

Original specification: OpenBCI Cyton (8 ch, 250 Hz), five simultaneous SSVEP targets with hi/lo refresh profiles, FBCCA with optional eTRCA, KuzuDB knowledge graph, TimescaleDB for telemetry only, two machines.
