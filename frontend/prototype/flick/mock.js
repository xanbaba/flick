// In-browser mock of the P3 backend, emitting the ARCHITECTURE.md §6.5 WebSocket messages and
// answering the §6.6 REST calls. EEG, PSD and scores are computed from the synthetic waveform in
// dsp.js; selections come from the dwell state machine, never from a script. The only scripted
// parts are partner utterances, LLM outputs and where the simulated pilot looks. Every sys.status
// carries a non-null input_badge so the dashboard can never present this as real (DEMO-3).

import { FS, NCH, Generator, psd, rhoScores, DwellTracker } from './dsp.js';
import { PERSONA_NAME, PROFILES, DECISION, CHANNELS, PRICE, buildSeed, TURNS, STATIC_INTENTS, STATIC_CANDIDATES } from './persona.js';

const BADGE = 'SIMULATED · BROWSER MOCK — NOT EEG';
const BUF = 500;
const CANCELLED = new Error('cancelled');
const nowS = () => Date.now() / 1000;
const rid = p => p + Math.random().toString(36).slice(2, 8);
const rand = (a, b) => a + Math.random() * (b - a);
const clone = o => JSON.parse(JSON.stringify(o));

export class MockServer {
  constructor({ startSeeded = false, profile = 'hi' } = {}) {
    this.onmessage = null;
    this.profileName = profile;
    this.profile = PROFILES[profile];
    this.gen = new Generator(this.profile.bandpass_low_hz);
    this.dwell = new DwellTracker(DECISION);
    this.buf = Array.from({ length: NCH }, () => new Float64Array(BUF));
    this.filled = 0;
    this.nodes = new Map();
    this.edges = new Map();
    this.seeded = false;
    this.localMode = false;
    this.autopilot = true;
    this.fsmState = 'UNSEEDED';
    this.trial = null;
    this.flickering = false;
    this.attended = null;
    this.attendedAt = 0;
    this.refractoryUntil = 0;
    this.tok = 0;
    this.turnIdx = 0;
    this.busy = false;
    this.sessionUsd = 0;
    this.selections = [];
    this.rhoWin = [];
    this.rhoAll = { sum: 0, n: 0 };
    this.viewers = 3;
    this.partnerOverride = null;
    if (startSeeded) {
      const { nodes, edges } = buildSeed();
      nodes.forEach(n => this.nodes.set(n.id, n));
      edges.forEach(e => this.edges.set(e.id, e));
      this.seeded = true;
      this.fsmState = 'IDLE';
    }
  }

  start() {
    this.t0 = performance.now();
    this.samples = 0;
    this.hopTimer = setInterval(() => this.hop(), 250);
    this.statusTimer = setInterval(() => this.status(), 1000);
    this.analyticsTimer = setInterval(() => this.analytics(), 2000);
    if (this.seeded) this.scheduleLoop(2500);
  }
  stop() {
    clearInterval(this.hopTimer); clearInterval(this.statusTimer); clearInterval(this.analyticsTimer);
    clearTimeout(this.loopTimer);
    this.tok++;
  }
  emit(type, payload) { if (this.onmessage) this.onmessage({ type, ts: nowS(), payload }); }

  // ---- client → server (schemas.py §6.3) ----
  receive(msg) {
    if (!msg || typeof msg.type !== 'string') { console.warn('mock: dropped malformed client message', msg); return; }
    if (msg.type === 'client.request_snapshot') {
      this.emit('graph.snapshot', this.snapshot());
      this.status();
      this.emit('spectator.link', this.spectatorLink());
      this.emit('fsm.state', { state: this.fsmState, detail: this.seeded ? 'listening' : 'awaiting onboarding' });
    } else if (msg.type === 'client.key_press') {
      const idx = Number(msg.key) - 1;
      if (Number.isInteger(idx) && idx >= 0 && idx < this.profile.frequencies.length) this.attend(idx);
      else console.warn('mock: key outside target range dropped', msg.key);
    } else console.warn('mock: unknown client message type', msg.type);
  }

  // ---- REST (§6.6) ----
  async rest(method, path, body = {}) {
    await new Promise(r => setTimeout(r, 40));
    const key = `${method} ${path}`;
    switch (key) {
      case 'GET /api/onboarding/status': return { seeded: this.seeded, node_count: this.nodes.size };
      case 'POST /api/onboarding/seed': return this.seed(body.bio, body.name);
      case 'POST /api/utterance': this.utterance(String(body.text || '')); return { ok: true };
      case 'POST /api/privacy/local_mode': this.localMode = !!body.enabled; this.status(); this.emit('spectator.link', this.spectatorLink()); return { local_mode: this.localMode };
      case 'POST /api/privacy/purge': return this.purge(body.scope);
      case 'POST /api/partner': this.partnerOverride = body.partner_id || null; return { partner_id: this.partnerOverride };
      case 'GET /api/spectator/link': return this.spectatorLink();
      case 'GET /api/graph': return this.snapshot();
      case 'POST /api/calibration/start': throw new Error('Cued blocks are not simulated in the browser mock');
      default: throw new Error(`mock: no handler for ${key}`);
    }
  }

  // ---- sensor loop: bci.eeg / bci.psd / bci.scores at 4 Hz ----
  attend(idx) { if (idx !== this.attended) { this.attended = idx; this.attendedAt = performance.now(); } }
  hop() {
    const due = Math.floor((performance.now() - this.t0) / 1000 * FS) - this.samples;
    const n = Math.max(1, Math.min(due, 125));
    const age = (performance.now() - this.attendedAt) / 1000;
    const ssvep = this.flickering && this.attended != null
      ? { freq: this.profile.frequencies[this.attended], phase: this.profile.phases[this.attended], age } : null;
    const data = this.gen.generate(n, ssvep);
    this.samples += n;
    for (let k = 0; k < NCH; k++) {
      const b = this.buf[k];
      b.copyWithin(0, n);
      b.set(data[k], BUF - n);
    }
    this.filled = Math.min(BUF, this.filled + n);
    this.emit('eeg.trace', { channels: CHANNELS, data, fs: FS });
    if (this.filled < BUF) return;
    const mean = new Float64Array(BUF);
    for (let i = 0; i < BUF; i++) { let s = 0; for (let k = 0; k < NCH; k++) s += this.buf[k][i]; mean[i] = s / NCH; }
    const { freqs, power } = psd(mean);
    const peaks = this.profile.frequencies.map(f => power[Math.round(f * 2)]);
    this.emit('eeg.psd', { freqs, power, peaks });
    const rho = rhoScores(mean, this.profile.frequencies);
    let d;
    if (performance.now() < this.refractoryUntil) {
      this.dwell.reset();
      const o = rho.map((v, i) => i).sort((a, b) => rho[b] - rho[a]);
      d = { winner_idx: o[0], margin: rho[o[0]] / (rho[o[1]] + 1e-9), above_threshold: rho[o[0]] >= DECISION.rho_threshold, dwell_count: 0, fired: false };
    } else d = this.dwell.update(rho);
    this.emit('bci.scores', { algorithm: 'fbcca', rho, winner_idx: d.winner_idx, margin: d.margin, above_threshold: d.above_threshold, dwell_count: d.dwell_count });
    this.rhoWin.push(rho);
    if (this.rhoWin.length > 8) this.rhoWin.shift();
    this.rhoAll.sum += rho.reduce((a, b) => a + b, 0) / rho.length; this.rhoAll.n++;
    if (d.fired) this.onFire(d.winner_idx, rho[d.winner_idx]);
  }

  onFire(idx, rho) {
    this.refractoryUntil = performance.now() + DECISION.refractory_s * 1000;
    if (!this.trial || !this.waiter || !this.fsmState.endsWith('_WAIT')) return;
    const w = this.waiter;
    this.waiter = null;
    w.resolve({ idx, rho, latency: (performance.now() - this.trial.shownAt) / 1000 });
  }

  // ---- 1 Hz status, 2 s analytics ----
  providers() {
    return this.localMode
      ? { llm: { name: 'openai_compat', healthy: true, local: true }, stt: { name: 'faster_whisper', healthy: true, local: true }, tts: { name: 'piper', healthy: true, local: true } }
      : { llm: { name: 'gemini', healthy: true, local: false }, stt: { name: 'deepgram', healthy: true, local: false }, tts: { name: 'elevenlabs', healthy: true, local: false } };
  }
  status() {
    const drops = Math.random() < 0.06 ? 1 + Math.floor(Math.random() * 2) : 0;
    const hz = 165 + rand(-0.15, 0.15);
    this.emit('sys.status', {
      input_source: 'mock', input_badge: BADGE, source: 'synthetic', connected: true, replay: false,
      local_mode: this.localMode, profile: this.profileName, measured_refresh_hz: hz,
      providers: this.providers(),
      stimulus_integrity: { measured_refresh_hz: hz, dropped_frames_last_s: drops, frame_interval_std_ms: rand(0.12, 0.3) },
      telemetry_dropped: 0,
      frequencies: this.profile.frequencies, cancel_idx: this.profile.cancel_idx,
      decision: { rho_threshold: DECISION.rho_threshold, margin_ratio: DECISION.margin_ratio, dwell_windows: DECISION.dwell_windows },
    });
    if (!this.localMode) {
      if (Math.random() < 0.08) this.viewers = Math.max(1, Math.min(14, this.viewers + (Math.random() < 0.6 ? 1 : -1)));
      this.flow('spectator', 'Spectator relay', 180, 'selections + spoken lines. No graph content.');
    }
  }
  analytics() {
    const n = this.selections.length;
    const mean = this.rhoWin.length ? this.profile.frequencies.map((_, i) => this.rhoWin.reduce((s, r) => s + r[i], 0) / this.rhoWin.length) : this.profile.frequencies.map(() => 0);
    const recent = this.rhoWin.length ? mean.reduce((a, b) => a + b, 0) / mean.length : 0;
    this.emit('analytics.summary', {
      accuracy_pct: null, itr_bits_per_min: null, cued_trials: 0,
      mean_rho_by_target: mean, selections_total: n,
      mean_selection_latency_s: n ? this.selections.reduce((s, x) => s + x.latency, 0) / n : 0,
      drift: this.rhoAll.n ? recent - this.rhoAll.sum / this.rhoAll.n : 0,
    });
  }
  spectatorLink() { return { url: this.localMode ? null : 'https://flick-live.example/watch', connected_viewers: this.localMode ? 0 : this.viewers }; }
  flow(stage, destination, bytes, description) { if (!this.localMode) this.emit('privacy.flow', { stage, destination, bytes, description }); }

  // ---- graph ----
  snapshot() { return { nodes: clone([...this.nodes.values()]), edges: clone([...this.edges.values()]) }; }
  activate(nodeIds, reason) {
    const ids = nodeIds.filter(id => this.nodes.has(id));
    const set = new Set(ids);
    const edgeIds = [...this.edges.values()].filter(e => set.has(e.source) && set.has(e.target)).map(e => e.id);
    ids.forEach(id => { this.nodes.get(id).last_accessed = nowS(); });
    this.emit('graph.activate', { node_ids: ids, edge_ids: edgeIds, reason });
  }
  learn(learn) {
    const nodes = [], edges = [], reinforced = [];
    for (const [id, kind, label] of learn.nodes) {
      if (this.nodes.has(id)) { const n = this.nodes.get(id); n.weight = Math.min(5, n.weight + 0.1); reinforced.push(id); continue; }
      const n = { id, label, kind, weight: 1, last_accessed: nowS() };
      this.nodes.set(id, n); nodes.push(n);
    }
    for (const [kind, source, target] of learn.edges) {
      const id = `${source}-${kind}-${target}`;
      if (this.edges.has(id) || !this.nodes.has(source) || !this.nodes.has(target)) continue;
      const e = { id, source, target, kind, weight: 1 };
      this.edges.set(id, e); edges.push(e);
    }
    if (nodes.length || edges.length) this.emit('graph.bloom', clone({ nodes, edges }));
    if (reinforced.length) this.activate(reinforced, 'reinforce');
  }

  // ---- onboarding (§14) ----
  async seed(bio, name) {
    if (this.seeded) return { seeded: true, node_count: this.nodes.size };
    const tok = ++this.tok;
    const step = async (detail, ms) => { this.fsm('UNSEEDED', detail); await this.sleep(ms, tok); };
    this.flow('seed', 'Gemini (Google)', (bio || '').length + 900, 'bio text, first pass: 40–60 nodes');
    await step('seed:extract', 1600);
    this.flow('seed', 'Gemini (Google)', 2400, 'bio text + first-pass graph, expansion');
    await step('seed:expand', 1400);
    await step('seed:embed', 800);
    await step('seed:insert', 450);
    this.fsm('UNSEEDED', 'seed:stream');
    const { nodes, edges } = buildSeed();
    if (name && name.trim()) nodes[0].label = name.trim();
    const order = this.bfs(nodes, edges);
    for (let i = 0; i < order.length; i += 10) {
      const batch = order.slice(i, i + 10);
      batch.forEach(n => this.nodes.set(n.id, n));
      const bEdges = edges.filter(e => !this.edges.has(e.id) && this.nodes.has(e.source) && this.nodes.has(e.target));
      bEdges.forEach(e => this.edges.set(e.id, e));
      this.emit('graph.bloom', clone({ nodes: batch, edges: bEdges }));
      await this.sleep(150, tok);
    }
    this.seeded = true;
    this.fsm('IDLE', 'listening');
    this.scheduleLoop(4000);
    return { seeded: true, node_count: this.nodes.size };
  }
  bfs(nodes, edges) {
    const byId = new Map(nodes.map(n => [n.id, n])), adj = new Map(nodes.map(n => [n.id, []]));
    edges.forEach(e => { adj.get(e.source)?.push(e.target); adj.get(e.target)?.push(e.source); });
    const seen = new Set(['user']), out = [byId.get('user')], q = ['user'];
    while (q.length) for (const nb of adj.get(q.shift())) if (!seen.has(nb)) { seen.add(nb); out.push(byId.get(nb)); q.push(nb); }
    nodes.forEach(n => { if (!seen.has(n.id)) out.push(n); });
    return out;
  }
  purge(scope) {
    if (!['graph', 'telemetry', 'all'].includes(scope)) throw new Error('scope must be graph | telemetry | all');
    if (scope !== 'graph') { this.selections = []; this.rhoAll = { sum: 0, n: 0 }; this.rhoWin = []; this.sessionUsd = 0; }
    if (scope !== 'telemetry') {
      this.tok++; clearTimeout(this.loopTimer);
      this.nodes.clear(); this.edges.clear(); this.seeded = false; this.busy = false;
      this.stopStimulus();
      this.emit('graph.snapshot', this.snapshot());
      this.fsm('UNSEEDED', 'graph purged');
    }
    return { purged: scope };
  }

  // ---- conversation autopilot ----
  setAutopilot(on) { this.autopilot = on; if (on && this.seeded && !this.busy) this.scheduleLoop(1500); }
  scheduleLoop(ms) {
    clearTimeout(this.loopTimer);
    this.loopTimer = setTimeout(() => {
      if (!this.seeded || this.busy) return;
      if (this.autopilot) this.nextTurn();
    }, ms);
  }
  nextTurn() {
    if (!this.seeded || this.busy) return;
    const turn = TURNS[this.turnIdx++ % TURNS.length];
    this.runTurn(turn);
  }
  utterance(text) {
    if (!this.seeded || this.busy || !text.trim()) return;
    const scripted = TURNS.find(t => t.utterance.toLowerCase() === text.trim().toLowerCase());
    this.runTurn(scripted || this.staticTurn(text.trim()));
  }
  staticTurn(text) {
    const p = this.partnerOverride ? this.nodes.get(this.partnerOverride) : null;
    return {
      partner_id: p ? p.id : 'unknown', partner_name: p ? p.label : 'Unknown speaker', confidence: p ? 1 : 0.4,
      utterance: text, retrieve: ['user'], intents: STATIC_INTENTS, static: true,
      attempts: [{ intent: Math.floor(Math.random() * 4), retrieve: ['user'], candidates: null, grounding: [], pick: Math.floor(Math.random() * 3) }],
      voice: 'elevenlabs', learn: { nodes: [], edges: [] },
    };
  }
  fsm(state, detail = '') { this.fsmState = state; this.emit('fsm.state', { state, detail }); }
  sleep(ms, tok) { return new Promise((res, rej) => setTimeout(() => (tok === this.tok ? res() : rej(CANCELLED)), ms)); }
  stopStimulus() { this.flickering = false; this.attended = null; this.trial = null; if (this.waiter) { this.waiter.reject(CANCELLED); this.waiter = null; } }
  showTargets(round, labels) {
    this.trial = { id: rid('t_'), round, labels, shownAt: performance.now() };
    this.flickering = false;
    this.attended = null;
    this.dwell.reset();
    return this.trial;
  }
  // Waits for the classifier to fire. With autopilot on, the simulated pilot reads the tiles for
  // cue_duration_s, sometimes glances at another tile, then looks at the planned one.
  waitSelection(plan, tok) {
    const trial = this.trial;
    const p = new Promise((resolve, reject) => { this.waiter = { resolve, reject }; });
    const timeout = setTimeout(() => { if (this.waiter) { const w = this.waiter; this.waiter = null; w.resolve(null); } }, 30000);
    (async () => {
      await this.sleep(1000, tok);
      if (trial !== this.trial) return;
      this.flickering = true;
      if (!this.autopilot) return;
      if (Math.random() < 0.45) {
        const others = [0, 1, 2, 3].filter(i => i !== plan && trial.labels[i]);
        this.attend(others[Math.floor(Math.random() * others.length)]);
        await this.sleep(rand(500, 800), tok);
      }
      if (trial === this.trial && this.autopilot) this.attend(plan);
    })().catch(e => { if (e !== CANCELLED) console.error('mock gaze', e); });
    return p.finally(() => { clearTimeout(timeout); this.flickering = false; this.attended = null; });
  }
  select(sel, round, labels) {
    const label = labels[sel.idx] ?? '';
    this.selections.push({ latency: sel.latency });
    this.emit('input.selection', { target_idx: sel.idx, label, round, confidence: Math.min(1, sel.rho / 0.7), source: 'mock' });
  }

  async runTurn(turn) {
    this.busy = true;
    const tok = ++this.tok;
    const cancel = this.profile.cancel_idx;
    const llmMs = () => (this.localMode ? rand(2200, 2900) : rand(900, 1500));
    const cost = { gin: 0, gout: 0, chars: 0, sttMin: 0 };
    const turnId = rid('turn_');
    try {
      this.fsm('TRANSCRIBING', this.localMode ? 'faster_whisper' : 'deepgram');
      const audioS = 1.2 + turn.utterance.split(' ').length * 0.28;
      this.flow('stt', 'Deepgram', Math.round(audioS * 32000), `${audioS.toFixed(1)} s of microphone audio`);
      cost.sttMin += audioS / 60;
      await this.sleep(this.localMode ? 1300 : 650, tok);
      const partner = this.partnerOverride && this.nodes.has(this.partnerOverride) && !turn.static ? { id: this.partnerOverride, name: this.nodes.get(this.partnerOverride).label, confidence: 1 } : { id: turn.partner_id, name: turn.partner_name, confidence: turn.confidence };
      this.emit('conv.transcript', { speaker: 'partner', text: turn.utterance, partner_id: partner.id, partner_name: partner.name, confidence: partner.confidence });
      this.fsm('GROUNDING', 'partner id + retrieval');
      this.flow('partner_id', 'Gemini (Google)', 700, 'partner utterance + known people');
      cost.gin += 600; cost.gout += 40;
      await this.sleep(420, tok);
      this.activate(turn.retrieve, 'retrieval');
      await this.sleep(260, tok);
      this.fsm('INTENT_GEN', turn.static ? 'static provider' : this.providers().llm.name);
      await this.sleep(turn.static ? 120 : llmMs(), tok);
      this.flow('intents', 'Gemini (Google)', 2100, 'partner utterance + 8 retrieved facts');
      cost.gin += 1400; cost.gout += 30;
      const intentLabels = [...turn.intents];
      let spokenText = null, attemptIdx = 0;
      while (spokenText == null) {
        const tr = this.showTargets('intent', [...intentLabels.slice(0, cancel), 'Cancel']);
        this.emit('conv.intents', { trial_id: tr.id, labels: intentLabels });
        this.fsm('INTENT_WAIT', 'awaiting selection');
        const attempt = turn.attempts[Math.min(attemptIdx, turn.attempts.length - 1)];
        const s1 = await this.waitSelection(attempt.intent, tok);
        if (!s1) { this.stopStimulus(); this.fsm('IDLE', 'No selection — listening again'); return; }
        this.select(s1, 'intent', tr.labels);
        if (s1.idx === cancel) { this.stopStimulus(); this.fsm('IDLE', 'cancelled'); return; }
        const scripted = !turn.static && s1.idx === attempt.intent;
        const intent = intentLabels[s1.idx];
        this.fsm('CANDIDATE_GEN', scripted ? this.providers().llm.name : 'static provider');
        await this.sleep(300, tok);
        this.activate(scripted ? attempt.retrieve : ['user'], 'retrieval');
        await this.sleep(scripted ? llmMs() : 150, tok);
        const candidates = scripted ? attempt.candidates : (STATIC_CANDIDATES[intent] || STATIC_CANDIDATES.Yes);
        const grounding = scripted ? attempt.grounding.filter(id => this.nodes.has(id)) : [];
        this.flow('candidates', 'Gemini (Google)', 2600, 'partner utterance, chosen intent + 8 facts');
        cost.gin += 1700; cost.gout += 110;
        const tr2 = this.showTargets('candidate', [...candidates, '', 'Cancel'].slice(0, 5));
        this.emit('conv.candidates', { trial_id: tr2.id, candidates, grounding });
        this.fsm('CANDIDATE_WAIT', intent);
        const plan = scripted ? attempt.pick : Math.floor(Math.random() * 3);
        const s2 = await this.waitSelection(plan === 4 ? cancel : plan, tok);
        if (!s2) { this.stopStimulus(); this.fsm('IDLE', 'No selection — listening again'); return; }
        this.select(s2, 'candidate', tr2.labels);
        if (s2.idx === cancel || s2.idx >= candidates.length) { attemptIdx++; this.fsm('INTENT_WAIT', 'cancelled — same labels'); await this.sleep(500, tok); continue; }
        spokenText = candidates[s2.idx];
      }
      this.stopStimulus();
      this.fsm('SPEAKING', this.providers().tts.name);
      const cached = !this.localMode && turn.voice === 'cache';
      const voice = this.localMode ? 'piper' : cached ? 'cache' : 'elevenlabs';
      if (voice === 'elevenlabs') { this.flow('tts', 'ElevenLabs', spokenText.length, 'the sentence text only'); cost.chars += spokenText.length; }
      const latency = voice === 'cache' ? rand(25, 60) : voice === 'piper' ? rand(60, 110) : rand(280, 520);
      await this.sleep(latency, tok);
      this.emit('conv.spoken', { text: spokenText, voice, cached, latency_ms: Math.round(latency) });
      await this.sleep(700 + spokenText.split(' ').length * 300, tok);
      this.fsm('LEARNING', 'reinforce + extract');
      this.flow('extraction', 'Gemini (Google)', 1900, 'utterance, spoken sentence + graph summary');
      cost.gin += 1500; cost.gout += 160;
      await this.sleep(this.localMode ? 1600 : 900, tok);
      this.learn(turn.learn);
      const items = this.localMode ? [] : [
        { provider: 'Gemini', detail: `${cost.gin} in / ${cost.gout} out tokens`, usd: cost.gin / 1000 * PRICE.gemini_in_per_1k + cost.gout / 1000 * PRICE.gemini_out_per_1k },
        { provider: 'ElevenLabs', detail: `${cost.chars} characters`, usd: cost.chars / 1000 * PRICE.elevenlabs_per_1k_chars },
        { provider: 'Deepgram', detail: `${(cost.sttMin * 60).toFixed(1)} s audio`, usd: cost.sttMin * PRICE.deepgram_per_minute },
      ];
      const turnUsd = items.reduce((s, i) => s + i.usd, 0);
      this.sessionUsd += turnUsd;
      this.emit('privacy.cost', { turn_id: turnId, items, turn_usd: turnUsd, session_usd: this.sessionUsd });
      await this.sleep(600, tok);
      this.fsm('IDLE', 'listening');
    } catch (e) {
      if (e !== CANCELLED) { console.error('mock turn failed', e); this.fsm('IDLE', 'turn failed'); }
    } finally {
      if (tok === this.tok) { this.busy = false; this.scheduleLoop(rand(4500, 6500)); }
    }
  }

  // Operator test hooks (SIM controls): real messages through the same path the backend uses.
  testPulse() {
    const ids = [...this.nodes.keys()];
    if (!ids.length) return;
    const start = ids[Math.floor(Math.random() * ids.length)];
    const hood = new Set([start]);
    for (const e of this.edges.values()) { if (hood.size > 7) break; if (e.source === start) hood.add(e.target); else if (e.target === start) hood.add(e.source); }
    this.activate([...hood], 'test');
  }
  testBloom() {
    if (!this.seeded) return;
    const anchors = ['sofia', 'elena', 'mateo', 'priya', 'rosie', 'trumpet', 'window_seat', 'coffee'].filter(id => this.nodes.has(id));
    const a = anchors[Math.floor(Math.random() * anchors.length)] || 'user';
    const id = rid('m_test_');
    this.learn({ nodes: [[id, 'Memory', `Test memory linked to ${this.nodes.get(a)?.label || 'Marcus'}`]], edges: [['INVOLVES', id, a], ['INVOLVES', id, 'user']] });
  }
}

export const MOCK_PERSONA_NAME = PERSONA_NAME;
