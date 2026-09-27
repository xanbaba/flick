# ARCHITECTURE

**Flick — a semantic brain–computer interface for assistive communication.**

## 0. Scope and implementation status

**Revision 2026-09-27: five-hour hackathon scope.** This replaces the previous
larger architecture. Deliver the spoken conversation loop, live Cortex
next/select input, onboarding, and persistent memory that updates and carries
context across turns. **Tiger Data is required for the sponsor challenge.**

This is the target, not a claim of completed implementation. At the scope review,
the repository had a working keyboard/SSVEP-oriented conversation pipeline and
Kuzu memory. Cortex acquisition, shared scanning, Tiger storage, and explicit
recent-conversation context still required implementation. Existing tests passing
does not establish that this target works.

`AGENTS.md` governs process. Its references to retired stimulus, replay, and DSP
features do not restore them to scope. Sections 5 and 6 specify the reduced
configuration and contracts; this document-only revision does not change runtime
interfaces or bypass their coordinated-edit process.

## 1. The product to deliver

A conversational partner speaks. Flick transcribes them and uses personal memory
plus recent conversation to generate three reply intents. A trained Emotiv mental
command moves a highlight; a jaw clench selects. Flick generates three sentences
for the chosen intent, the user selects one, and Flick speaks it. Supported new
facts are committed to Tiger and appear in the memory graph.

One browser screen contains large static choice tiles, transcript, memory graph,
and minimal input/storage status. The graph exists after onboarding or loading an
existing profile, remains visible during conversation, and updates after learning.
There is no flicker or automatic timed scanning.

| Round | Ordered tiles | Cancel index, zero-based |
|---|---|---|
| Intent | Three semantic intents, Cancel | 3 |
| Candidate | Three sentence slots, Cancel | 3 |

Cancel during intent selection returns to listening. Cancel during candidate
selection restores the same intent labels with a fresh trial ID. Candidate
fallback is `[chosen intent, "", "", Cancel]`: preserve the selected intent
verbatim, disable blank slots, and visibly disclose fallback generation.

### 1.1 Two kinds of memory

- **Personal graph:** biography, people, relationships, preferences, experiences,
  and supported new facts, persisted across restarts.
- **Recent conversation:** ordered, speaker-labelled utterances and completed
  replies. Supply the most recent six exchanges to retrieval and generation so
  “How was it?” can refer to the vacation just discussed.

A vector search for “How was it?” alone is not conversational context. Do not
claim continuity merely because fact extraction or a graph exists.

### 1.2 Sponsor integration

Tiger Data must store and serve the actual profile, memory graph, embeddings,
and conversation turns. Onboarding, both retrieval rounds, learning, and restart
recovery must use that store. A DSN, unused table, or telemetry-only connection
does not satisfy the intended integration. Use PostgreSQL with TimescaleDB and
pgvector on Tiger; detailed time-series analytics is outside this deadline.

Keep existing Gemini generation and configured ElevenLabs speech integration.
Do not add sponsor features unrelated to the core conversation.

## 2. Decisions and demo integrity

### 2.1 Hardware

Use Emotiv EPOC X through Launcher/Cortex on one PC. Verify account permissions,
actual stream fields, timestamps, and quality scale on the team's headset.
Required inputs are mental commands (`com`), facial activity (`fac`), and device/
signal-quality information (`dev`, `eq`). Band power and raw EEG are not required.
No alternate headset integration or hidden device fallback is in scope.

### 2.2 Interaction

Next is a trained `push` mental command; select is a lower-face jaw clench.
P1 detects actions without knowing labels, tile indices, or trial IDs. P3 owns
scan state and converts accepted actions into selections. Renderers display that
state and never calculate an independent highlight.

### 2.3 Detector starting values

| ID | Decision |
|---|---|
| DSP-1 | Next: matching `push`, power at least 0.45 for 0.5 seconds. |
| DSP-2 | Select: matching `clench`, lower-face power at least 0.5 for 0.2 seconds. |
| DSP-3 | Shared 0.8-second refractory after either event; release before the same sustained action fires again. |
| DSP-4 | Reset holds on low power, action change, poor/missing quality, disconnect, or a sample gap over 0.5 seconds. |
| DSP-5 | Facial activity above 0.3 overlapping next marks contamination; expose the flag without a diagnostic chart. |
| DSP-6 | No live triggers until session, trained/loaded profile, and fresh required streams confirm readiness. |

These are configurable starting values, not measured performance claims. Use
elapsed event time, not sample counts. Verify Cortex-to-normalized field mapping;
do not assume illustrative array positions or quality units are the real API.

### 2.4 Software

| ID | Decision |
|---|---|
| SW-1 | Python 3.11 and uv; FastAPI/uvicorn backend. |
| SW-2 | Existing Vite/React/TypeScript/Tailwind frontend, one conversation view. |
| SW-3 | Tiger PostgreSQL/TimescaleDB/pgvector is the authoritative memory store. |
| SW-4 | CPU MiniLM, 384 dimensions; deterministic embeddings only with a consistent, recorded embedding space. |
| SW-5 | Preserve existing NumPy facility-location selection; no new selection library. |
| SW-6 | Preserve Gemini → configured OpenAI-compatible → configured Gradient → explicit static generation fallback. |
| SW-7 | Preserve Deepgram → installed local faster-whisper → manual text fallback. |
| SW-8 | Preserve runtime audio cache → configured ElevenLabs → installed Piper → browser speech. |
| SW-9 | Python inference and its deployment dependencies are CPU-only; no CUDA requirement. |
| SW-10 | No durable mirror, outbox, or offline learning. Failed persistence is reported as failure. |

### 2.5 Demo integrity

1. No hidden manual triggering of headset selections. Keyboard development input
   always displays **KEYBOARD INPUT** and is never described as headset input.
2. Live BCI displays **NEXT: MENTAL COMMAND** and **SELECT: JAW CLENCH (MUSCLE)**.
   Do not claim thought reading or isolated neural origin.
3. Manual partner text bypasses only the microphone, never secretly selects tiles,
   and is marked as a scripted/manual prompt.
4. Replay and synthetic-source products are omitted. If old tools are used for
   development, outputs remain labelled **REPLAY** or **SYNTHETIC SIGNAL**;
   they cannot establish live headset success.
5. Show actual acquisition readiness and storage availability. A browser socket
   connection is not a trained headset; local PostgreSQL is not Tiger Cloud.
6. Show only measured or known values. Hide unfinished analytics/cost panels.
   Announce memory as saved or learned only after confirmed database commit.
7. Disclose cloud memory, LLM/STT/TTS use and the jaw-clench modality. Use only a
   consented configured voice; never claim all data stays on the machine.
8. Report actual acceptance results. Earlier flicker experiments do not validate
   this next/select implementation.

## 3. Topology and turn lifecycle

```text
EPOC X → Emotiv Launcher / Cortex
             ↓ secure WebSocket
P1: Cortex bridge + next/select detectors
             ↓ ZMQ PUB 5555
P3: FastAPI backend, shared scan, conversation, memory
             ↔ Tiger PostgreSQL + TimescaleDB + pgvector
             ↔ WebSocket / HTTP
P4: one browser conversation screen + memory graph + playback
```

Launch `python -m sensor.main`, the existing backend, and the existing frontend.
Remove P2/stimulus from `run.sh`. Retire `stim.*`, port 5557, and stimulus socket
ownership in adapters. Training happens before the demo through available Emotiv
tooling; a P3→P1 control channel is not required for this reduced scope.

Authorize/load the trained profile before the demo. No model loading, database
calls, blocking disk work, or unrelated network calls in P1's acquisition loop.
Cortex acquisition itself is the required network connection.

```text
UNSEEDED --atomic onboarding--> IDLE
IDLE → TRANSCRIBING → GROUNDING → INTENT_GEN → INTENT_WAIT
INTENT_WAIT --intent--> CANDIDATE_GEN → CANDIDATE_WAIT
INTENT_WAIT --Cancel/timeout--> IDLE
CANDIDATE_WAIT --Cancel--> INTENT_WAIT (same labels, new trial)
CANDIDATE_WAIT --timeout--> IDLE
CANDIDATE_WAIT --sentence--> SPEAKING → LEARNING → IDLE
```

One active turn at a time. Retrieve before both generation rounds. Complete the
bounded learning attempt before accepting the next turn so successful writes are
available immediately. Errors must leave a usable state with a visible reason,
not strand the FSM in GROUNDING or generation. If storage is unavailable, report
it and do not fabricate an empty or seeded personal memory.

## 4. Implementation surface

| Area | Deadline work |
|---|---|
| Shared | Update `shared/{schemas,config,bus}.py`, matching frontend types, and core config together. |
| Sensor | Add `sensor/main.py`, Cortex normalization and next/select detection; small modules suffice. |
| Inputs | Add `inputs/{bci,scan}.py`; update keyboard for the same scan controller. |
| Backend | Preserve orchestrator/services/providers; add database integration and bounded recent-turn context. |
| Frontend | Adapt dashboard, CandidatePanel, transcript, MemoryBrain and status; no separate `/pilot`. |
| Storage | Add reviewed forward migrations and a bounded Kuzu import tool; preserve original data. |
| Prompts | Update selection wording/counts and add speaker-labelled recent conversation. |
| Tests | Cover detectors, scan, context, real database persistence, and the retained end-to-end flow. |

Unused legacy modules may remain but must not be active product paths. Do not
modernize the prototype or delete historical data to tidy scope. Coordinate paths
under AGENTS.md; this table does not reassign another contributor's files.

## 5. Configuration

Target delta for the coordinated runtime revision, not the current config file.
Retain working provider, retrieval, generation-recovery, extraction,
reinforcement, and runtime voice/cache settings unless replaced here.

```yaml
input:
  adapter: keyboard           # keyboard | bci; use bci for the live demo
emotiv:
  cortex_url: wss://localhost:6868
  profile: flick-pilot
  headset_id: auto
  streams: [com, fac, dev, eq]
  min_contact_quality: 3      # verify normalized scale on actual device
scan:
  trial_timeout_s: 60
  hold_after_select_s: 0.6
  start_idx: 0
triggers:
  refractory_s: 0.8
  contamination_threshold: 0.3
  max_sample_gap_s: 0.5
  mental_command: {action: push, min_power: 0.45, hold_s: 0.5}
  jaw_clench: {action: clench, min_power: 0.5, hold_s: 0.2}
database:
  memory_pool_max: 5
  query_timeout_s: 0.3
  write_timeout_s: 1.0
graph:
  profile_id: user
  embedding_dim: 384
conversation:
  recent_exchanges: 6
  context_max_chars: 12000
generation:
  n_intents: 3
  n_candidates: 3
  max_tokens: 2048
  timeout_s: 12.0
  transient_retries: 1
  retry_delay_s: 0.5
  retry_jitter_s: 0.25
  min_attempt_budget_s: 2.0
voice:
  cache_first: true
  cache_dir: ./data/audio_cache
  playback_timeout_s: 30
```

Remove old `mode`, EEG/DSP/stimulus/classify/decision/calibration and Kuzu path
requirements from active configuration. Do not add spelling, replay, telemetry,
spectator, cost, or outbox configuration. Disable omitted services during the
transition. Validate positive bounds, finite thresholds, and required streams.
New tunable constants belong here and in runtime config, not scattered code.

Environment: add `TIGER_DSN`; allow `LOCAL_PG_DSN` only for explicit development/
integration tests. Migrate legacy `TIMESCALE_DSN` deliberately. Keep
`EMOTIV_CLIENT_ID`, `EMOTIV_CLIENT_SECRET` and existing provider credentials.
Never print or commit values. A local database is not automatic failover and does
not demonstrate the Tiger Cloud sponsor integration.

## 6. Reduced contracts

Keep message `type`, UNIX-seconds `ts`, typed validation, and Python/TypeScript
parity. Browser envelopes remain `{type, ts, payload}`. Implement the next contract
revision coherently across producers and consumers.

### 6.1 P1 → P3 and selections

| Message | Required content |
|---|---|
| `bci.trigger` | Unique event ID, original/normalized timestamp, role `next/select`, kind `mental_command/jaw_clench`, strength, contamination. No tile/trial identity. |
| `bci.status` | Actual `emotiv` source, connection/readiness and reason, headset identity, loaded profile/trained actions, available contact/signal quality. Missing measurements are null. |
| `input.selection` | Current trial ID, target index, confidence, source `bci/keyboard`, algorithm `step_scan` for BCI, trigger kind where applicable, accepted next count (`moves`). |

Normalize Cortex timestamps to the backend-comparable event clock. P3 rejects
events predating trial activation, duplicate/stale events, and events for closed
interaction periods. Loss of fresh readiness disarms input. Select strength is
BCI confidence, not accuracy; manual input uses 1.0 with its badge.

### 6.2 Browser interaction

`client.key_press` carries displayed `trial_id`, timestamp and key: `n`, `s`, or
`1`–`4`. Only the keyboard adapter accepts it. Ignore shortcuts while typing.
Keep `client.request_snapshot` and correlated `client.playback_complete` with
existing playback ID/outcome semantics.

| Server event | Required behavior |
|---|---|
| `scan.targets` | Authoritative `{trial_id, labels, round, cancel_idx, highlight_idx}`. |
| `scan.highlight` | `{trial_id, highlight_idx}`; discard mismatched-trial updates. |
| `scan.selected` | `{trial_id, target_idx, hold_s}`; visual confirmation only. |
| `scan.idle` | Reason; clears/disables interaction. |
| `conv.transcript` | Text, speaker/partner identity, actual confidence where available. |
| `conv.intents`, `conv.candidates` | Current trial, four-slot list, Cancel index, generation source/fallback reason; candidates retain validated grounding IDs. |
| `conv.spoken` | Existing text, voice tier/cache/latency/audio and correlated playback ID/deadline. |
| `graph.snapshot`, `graph.activate`, `graph.bloom` | Existing stable node/edge IDs, weights, activation and accepted new memories. |
| `fsm.state` | State and detail, with no spelling state. |
| `sys.status` | Adapter/badge, actual readiness/modality, provider health, memory availability and actual destination; no invented metrics. |

Reconnect restores graph, recent transcript, status, current targets/highlight,
matching conversation metadata and then FSM. Preserve current trial ID; never
replay audio or reset highlight. Disconnected views cannot submit input; disable
interaction until authoritative state is restored.

### 6.3 REST and playback

Preserve health, graph, onboarding, partner, utterance, and input-swap routes.
Swap supports only `keyboard/bci`, only idle/unseeded, with listener cleanup and
rollback on failed startup. Known-person override is session-scoped.

Do not expose unfinished mode/spelling, replay/session, training-job, cued-block,
analytics, timeline, cost/ledger, purge, or spectator features. Disabled routes
return explicit unavailable responses or normal 404, never fake acceptance.

Support one active conversation/playback browser. Prevent extra connections from
becoming duplicate audio recipients or input controllers; a simple single-client
restriction suffices without a multi-view ownership protocol. Keep audio unlock
and acknowledgment only after audio ends/stops. Missing acknowledgment or playback
disconnect keeps capture gated until restart, as implemented. Preserve manual
partner text for recovery. Playback deadline remains separate from scan timeout.

## 7. Live input and scan

Verify Cortex authorization/session/profile/subscription behavior against the
installed tooling. Train neutral/push through available Emotiv tooling before
the demo, then verify the saved profile reloads and emits usable commands. Build
only a minimal utility if that tooling cannot perform required training. No
product training wizard or training during an active conversation.

P1 applies section 2.3 to fresh normalized samples. Missing facial/quality data is
not evidence of clean/ready input. Sustained actions fire once and require release.
Preserve contamination disclosure even when the next event is accepted.

Keep the InputSource lifecycle and share one backend ScanController:

1. Setting targets closes prior state, clears old queued input, resets moves,
   validates final Cancel, starts at the first enabled configured slot, and
   publishes `scan.targets` with a fresh ID.
2. Next advances once to the next enabled slot and wraps. No timer movement.
3. Select snapshots the highlight, closes the trial, emits one Selection and
   `scan.selected`, then holds its visual result for the configured duration.
4. If next/select arrive together, select uses the pre-event highlight; discard
   the competing next. Do not carry held actions into a new screen.
5. Timeout closes both adapter and orchestrator state, emits `scan.idle`, and
   returns to listening with “No selection — listening again”.

No selection during startup, generation, speaking, learning, confirmation hold,
or a closed trial. Reject blank/out-of-range picks. Hot-swap cannot carry queued
triggers into the replacement adapter.

## 8. Tiger memory and migration

### 8.1 Storage model

Use one Tiger PostgreSQL deployment with TimescaleDB and pgvector available.
Ordinary transactional tables suffice for the core; no hypertables, compression
policies, telemetry, or continuous aggregates are required for this delivery.

| Table | Core fields and constraints |
|---|---|
| `profiles` | ID, display name, biography, embedding backend/model/dimension, timestamps. |
| `nodes` | Profile + stable node ID, kind, name/text, retained attributes, `vector(384)`, finite weight, creation/access times. |
| `edges` | Profile + stable edge ID, kind, endpoints, weight/count, optional strength, reinforcement time; unique profile/kind/endpoints. |
| `conversation_turns` | Stable turn ID, profile/partner, incoming utterance, chosen intent, selected reply, playback outcome, completion time; distinguish failed output from spoken output. |

Profile-scoped keys/foreign keys prevent cross-profile edges. Retain all six node
kinds and current valid relation pairs; validate endpoint kinds in the write
transaction. Preserve LIKES/DISLIKES and strength in [0,1]. Self Person remains
`user`, `relationship=self`, agreeing with profile name. Memory content belongs
in `text`; other display content in `name`. Reject blank content and non-finite/
mismatched vectors or weights. Preserve attributes and factual source attribution.

### 8.2 Service behavior

Retain GraphService's domain results and needed operations: schema/seed, snapshot,
vector_search, expand, reinforce, upsert_node/edge, people, node_count, get_node,
edges_among, get_embeddings, transaction and close. Reconcile the async boundary:
asyncpg owns remote I/O; CPU embeddings/NumPy work stays off the event loop. Do not
wrap blocking SQL in an async function or nest event loops.

Use profile-filtered pgvector cosine search and bounded, cycle-safe undirected
neighbor expansion. Preserve NumPy facility selection and stable ID tie-breaking.
Index for correct bounded retrieval; defer extensive tuning. Measure actual demo
response time, not an unproven 150 ms remote retrieval claim.

Choose one embedding space per profile. Use cached CPU MiniLM where available;
otherwise use deterministic embeddings consistently and record the backend. Never
silently mix hash and MiniLM vectors. Re-embed imported facts consistently if old
provenance is unknown. Explicitly handle unavailable/zero vectors; do not turn
missing embeddings into apparent similarity.

### 8.3 Commit and failure semantics

Atomic onboarding inserts profile, self Person and accepted graph in one remote
transaction. Each logical learning update commits reinforcement/new facts and its
turn record consistently. Finish provider/embedding work before opening the write
transaction. Update accepted snapshots/blooms only after commit.

Bound database calls. Read failure reports memory unavailable and ends the turn
cleanly; never substitute Marcus or an empty graph. Write failure shows “Memory
update failed” without announcing additions as learned. No offline acceptance,
durable mirror, outbox, pending queue, or replay protocol. If commit outcome is
uncertain, report uncertainty and reconcile persisted state before continuing
writes; never blindly retry increments. Stable turn IDs and uniqueness constraints
prevent accidental duplicate turn insertion.

Startup loads profile/graph and bounded recent conversation from Tiger. No profile
means onboarding; unreachable storage means unavailable, not unseeded. Close pools/
workers cleanly. Optional process-local caches do not authorize offline success.

### 8.4 Migration gate

Add a forward migration; do not rewrite applied `001_timescale.sql`. Export the
needed Kuzu profile without changing the original. Preserve a rollback copy,
import in a PostgreSQL transaction, and compare identity, IDs, facts, relations,
weights and counts. Verify both retrieval rounds, new learning, and restart
persistence against real PostgreSQL/pgvector before retiring Kuzu runtime use.
Local integration tests are useful; separately prove the same core path uses the
actual Tiger deployment for the sponsor demo. Never commit personal exports,
recordings, database files, or secrets.

## 9. Onboarding and conversational memory

### 9.1 Onboarding

Keep the editable name/biography form. Require a nonblank supplied name; do not
silently replace it with Marcus. Generate/validate supported facts, embed, and
commit atomically before graph blooms. Existing first-pass/repair behavior is
sufficient; no required second expansion pass or 150–300-node quota. A smaller
accurate graph is acceptable.

Retain onboarding's existing 4000-token per-pass allowance within its configured
generation deadline; the ordinary reply token limit does not replace it.

Retain concurrent/reseed 409 protection and custom-biography failure as retryable
503 without changing the graph. The bundled persona is permitted only for the
unchanged demo name/biography, visibly disclosed as fixture-derived, and still
persisted to Tiger. Remove fixture claims not established by its biography. Do
not rewrite effective validation merely to change its implementation style.

### 9.2 Recent conversation

Maintain a bounded buffer of recent completed exchanges for the active profile/
partner with stable turn identity and speaker labels. Persist turns in Tiger and
reload after restart. Clear/partition conversational context on partner changes;
personal graph memory remains profile-scoped.

Supply recent turns, the current utterance, and graph facts as separate labelled
inputs to both generation rounds. Include recent turns in retrieval context so
pronouns/topic references have antecedents. Apply the configured count/character
cap; no summarization service or extra LLM query-rewrite stage. An unknown
antecedent should produce a clarification option, not invented context.

Record what actually happened: distinguish partner words from the user's chosen
reply and playback outcome. Unchosen candidates are not user statements. Questions
are not confirmed facts. A partner saying “I went to Rome” does not mean the user
went to Rome. Pass attributions/recent context into extraction too. Graph grounding
IDs refer only to supplied graph facts; do not invent IDs for conversational text.

### 9.3 Retrieval and learning

Preserve current stages: top 25 vector seeds, two-hop expansion capped at 60,
partner boost, and NumPy selection of eight facts, using existing config. Round
two adds the chosen intent. Render stable fact IDs in prompts and filter unknown
grounding IDs from output.

Preserve extraction threshold (0.7), new-node cap (4), dedup threshold (0.88), and
bounded reinforcement settings. Search duplicates within the intended kind rather
than filtering an all-kind top-five result that can hide valid duplicates. Keep
factual provenance and relations. Extraction failure is reported, never replaced
with manufactured memory. Successful learning must be visible and retrievable
next turn and after restart.

Keep useful graph activation and stable snapshot reconciliation. Commit then bloom
new nodes and refresh weights. Exact traversal animation, separate selected-eight
visualization, and history timeline are not delivery gates.

## 10. Generation and speech

Intent prompts/parsers/fallbacks produce three distinct labels of one to three
words, including affirmative, negative/deflecting, and question directions.
Replace “choose by looking” with next/select scanning. Cancel is application-owned.
Candidates are three natural first-person sentences for the selected intent,
varying length and using supplied facts/attributed conversation only. Preserve
names, relationships and terms of address without inventing details.

Keep existing generation budgets: one shared 12-second stage deadline, bounded
transient retry, JSON repair and explicit fallback provenance. Keep provider
chains; do not rewrite them for this migration. Automatic partner identification
may remain if working; known-person override suffices.

Keep 16 kHz mono sounddevice capture and webrtcvad with existing 30 ms frames,
three-frame speech start, and 25-frame silence end. The 400 ms minimum checks
utterance duration excluding terminal silence; short noises cannot pass merely
because 750 ms of silence was appended. Retain the two-word filter and actual STT
confidence. Do not spend the deadline retuning unrelated STT policy.

Hard-gate the microphone in the capture callback before playback, and rearm only
after confirmed completion under existing rules. Preserve runtime caching,
configured voice, Piper/browser fallback, measured voice latency and correlated
completion. Full-response ElevenLabs audio suffices; omit streaming, enrollment,
and prerender tooling. A cloned voice requires prior consent; otherwise use an
existing fallback voice.

## 11. One frontend, minimal status

Adapt production React, not the prototype. Show the initial/updated MemoryBrain,
transcript, large four-tile scan area, clear highlight/selection confirmation,
source/modality badges, provider/fallback status, and actual memory availability/
destination. Preserve imperative graph instance lifetime and stable ID/weight
reconciliation. Show failures plainly without fake values.

Retain keyboard shortcuts with trial IDs only in keyboard mode, disabled blank
choices, input suppression while typing, audio unlock, reconnect backoff and
authoritative restoration. Only one active conversation browser is supported.

Hide obsolete EEG/PSD/correlation/refresh displays, spelling/mode controls,
analytics, costs, ledger/purge controls and spectator QR. Keep a short accurate
disclosure that memory/conversation are stored in Tiger and configured providers
receive data needed for their calls. No manual offline switch, claim that the
graph never leaves the machine, or nonfunctional deletion button. Detailed privacy
tooling is omitted, not claimed as implemented.

## 12. Explicitly outside this deadline

- Spelling, binary tree integration, lexicon, suggestions and spelling endpoints.
- Separate `/pilot`, dual-view ownership protocol, feedback-tone polish, detailed
  band-power/muscle/headset panels.
- Synthetic-source framework, recording, manifests, replay, training wizard/jobs.
  Small deterministic detector/scan test inputs remain required.
- Durable mirror/outbox, offline learning, queued deletion and recovery ledger.
- Telemetry, hypertables/aggregates, analytics/ITR, automated cued-block product,
  learning-event ledger and MemoryTimeline.
- Streaming TTS, enrollment and prerecorded/prerendered sentence tooling.
- Cost/ledger UI, purge, spectator/QR/relay/domain.
- Prototype modernization, unrelated provider refactoring, extensive retrieval
  tuning, and repository-wide cleanup.
- SSVEP/flicker, stimulus process, FBCCA/eTRCA, LSL and raw-EEG DSP.

Useful existing fallback/cache code may remain. Omission means no implementation
work or exposed unfinished feature, not mass deletion. Never disable failing tests
for retained behavior. Retire/update obsolete-feature tests explicitly with the
approved scope migration.

## 13. Remaining delivery sequence

1. Coordinate reduced config/contracts and launcher; prove actual Cortex events
   and Tiger connectivity/extension availability immediately.
2. Implement bridge/detectors and shared scan with keyboard development input.
3. Connect the conversation UI/FSM to scan and preserve playback.
4. Port graph/onboarding/learning to Tiger, import needed data, and verify real-
   database two-turn/restart behavior before removing Kuzu runtime use.
5. Add bounded attributed conversation context to retrieval/generation/extraction.
6. Integrate visible graph learning, failure recovery and the reduced screen.
7. Reserve the final hour for tests, actual-headset rehearsal and bug fixes. No
   optional features or broad refactors during that period.

Input/UI and memory/context can proceed across the existing human team after
agreeing on contracts/ownership. This is a deadline plan, not a promise of untested
integrations. Tiger and live Cortex are required; neither can be silently replaced
to claim completion.

## 14. Acceptance and honest failure handling

| Gate | Required evidence |
|---|---|
| Real input | Saved/trained profile loads; live mental command advances and jaw clench selects. Quality/readiness loss disarms. |
| Detector/scan | Timestamp tests cover holds, release, refractory, stale/duplicate events, contamination, simultaneous actions, wrapping/disabled tiles, timeout and Cancel. |
| Full turn | Real microphone → intents → Cortex selection → candidates → Cortex selection → audible response → confirmed microphone rearm. |
| Tiger core | Actual Tiger-backed onboarding, both retrieval rounds, reinforcement/new fact, graph update and restart persistence; label local-only results. |
| Conversation | Establish a vacation, ask “How was it?”, verify intents/candidates refer to that vacation. |
| Attribution | “Were you in Rome?” alone creates no confirmed vacation; partner experiences do not become the user's experiences. |
| Learning | Supported new fact blooms after commit, is retrieved next turn, and survives restart; duplicate mention creates no equivalent new node. |
| Failure | Storage/generation failure leaves a recoverable visible state; no fake seed/save/bloom, blind write retry, or stranded FSM. |
| Playback/reconnect | No self-transcription, duplicate playback, stale-trial selection, or audio replay; missing acknowledgment keeps capture gated. |
| Build | Full pytest, Ruff lint/format and frontend tests/build pass for retained behavior. Rehearse on the actual PC. |

Before claiming reliable live control, manually record 20 cued selections (target
at least 90% correct) and a two-minute no-select period (target at most one
unintended select). A paper/operator tally suffices; no calibration dashboard is
required. Report observed results and failures, not assumed success.

Automated provider tests use stubs, not credentials or downloads. Real database
integration uses an isolated service; target Tiger/headset checks are separate
explicit rehearsals. Never call unrun hardware/cloud checks passed. If a core gate
fails, disclose it rather than describe keyboard as live Cortex or Kuzu/local
storage as Tiger Cloud.
