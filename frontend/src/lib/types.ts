// Hand-mirrored from shared/schemas.py (ARCHITECTURE.md §6). Keep in sync per AGENTS.md §4:
// any change to schemas.py updates this file in the same commit.

// ---- 6.1 Selection contract ----
export interface Selection {
  type: 'input.selection';
  ts: number;
  trial_id: string;
  target_idx: number;
  confidence: number;
  source: string; // "ssvep" | "keyboard" | "replay" | "emotiv"
  algorithm: string | null; // "fbcca" | "etrca" | null
}

// ---- 6.2 ZMQ P1 → P3 (bci.) ----
export interface EegChunk { type: 'bci.eeg'; ts: number; fs: number; channels: string[]; data: number[][]; railed: boolean[] }
export interface PsdFrame { type: 'bci.psd'; ts: number; freqs: number[]; power: number[]; peaks: number[] }
export interface TargetScores {
  type: 'bci.scores';
  ts: number;
  algorithm: 'fbcca' | 'etrca';
  rho: number[];
  winner_idx: number;
  margin: number;
  above_threshold: boolean;
  dwell_count: number;
}
export interface SensorSelection { type: 'bci.selection'; ts: number; trial_id: string; target_idx: number; rho: number; margin: number; algorithm: 'fbcca' | 'etrca' }
export interface SensorStatus {
  type: 'bci.status';
  ts: number;
  source: 'cyton' | 'synthetic' | 'replay';
  connected: boolean;
  configured: boolean;
  samples_received: number;
  dropped_samples: number;
  railed_channels: number[];
}

// ---- 6.3 WebSocket dashboard → P3 (client.) ----
export interface KeyPress { type: 'client.key_press'; ts: number; key: string } // "1".."5"
export interface RequestSnapshot { type: 'client.request_snapshot'; ts: number }
export interface PlaybackComplete {
  type: 'client.playback_complete'; ts: number; playback_id: string;
  outcome: 'completed' | 'failed';
}
export type ClientMessage = KeyPress | RequestSnapshot | PlaybackComplete;

// ---- 6.4 ZMQ P3 → P2 (stim.) ----
export interface ShowTargets { type: 'stim.show_targets'; ts: number; trial_id: string; labels: string[]; round: 'intent' | 'candidate' | 'speller'; cue_idx: number | null }
export interface StimControl { type: 'stim.control'; ts: number; action: 'idle' | 'start_flicker' | 'stop_flicker' | 'message'; message: string | null }

// ---- 6.5 ZMQ P2 → P3 (stim.) ----
export interface StimulusProfile {
  type: 'stim.profile';
  ts: number;
  profile: 'hi' | 'lo';
  measured_refresh_hz: number;
  frequencies: number[];
  phases: number[];
  cancel_idx: number;
  window_s: number;
  bandpass_low_hz: number;
  fbcca_subband_low_hz: number[];
}
export interface StimulusOnset { type: 'stim.onset'; ts: number; trial_id: string; frequencies: number[] }
export interface StimulusIntegrity { type: 'stim.integrity'; ts: number; measured_refresh_hz: number; dropped_frames_last_s: number; frame_interval_std_ms: number }

export type BusMessage =
  | Selection | EegChunk | PsdFrame | TargetScores | SensorSelection | SensorStatus
  | ShowTargets | StimControl | StimulusProfile | StimulusOnset | StimulusIntegrity;

// ---- 6.6 analytics.summary payload ----
export interface AnalyticsSummary {
  accuracy_pct: number | null;
  itr_bits_per_min: number | null;
  cued_trials: number;
  mean_rho_by_target: number[];
  selections_total: number;
  mean_selection_latency_s: number;
  drift: number;
}

// ---- 6.7 Graph payload types ----
export type NodeKind = 'Person' | 'Place' | 'Thing' | 'Activity' | 'Need' | 'Memory';
export interface GraphNode { id: string; label: string; kind: NodeKind; weight: number; last_accessed: number }
export interface GraphEdge { id: string; source: string; target: string; kind: string; weight: number }

// ---- WebSocket P3 → dashboard (ARCHITECTURE.md §6.5 table). Envelope {type, ts, payload}. ----
// sys.status is assembled by the backend, not a pydantic model. The live payload
// uses a provider-health map, and refresh / integrity are null until P2 exists.
export interface SysStatusPayload {
  input_source: string;
  input_badge: string | null; // rendered high-contrast whenever non-null (§7.6)
  source: 'cyton' | 'synthetic' | 'replay';
  connected: boolean;
  replay: boolean;
  local_mode: boolean;
  profile: 'auto' | 'hi' | 'lo';
  measured_refresh_hz: number | null;
  providers: Record<string, Record<string, boolean>>;
  stimulus_integrity: {
    measured_refresh_hz: number;
    dropped_frames_last_s: number;
    frame_interval_std_ms: number;
  } | null;
  telemetry_dropped: number;
  frequencies?: number[];
  cancel_idx?: number;
  decision?: { rho_threshold: number; margin_ratio: number; dwell_windows: number };
}
export interface PrivacyCostItem { provider: string; detail: string; usd: number } // UNSPECIFIED

export interface WsPayloads {
  // Generation token limits and deadlines come from server config; changing
  // those limits does not change the intent or candidate payload shapes.
  'eeg.trace': { channels: string[]; data: number[][]; fs: number };
  'eeg.psd': { freqs: number[]; power: number[]; peaks: number[] };
  'bci.scores': Omit<TargetScores, 'type' | 'ts'>;
  'input.selection': { target_idx: number; label: string; round: 'intent' | 'candidate' | 'speller'; confidence: number; source: string };
  'conv.transcript': { speaker: string; text: string; partner_id: string | null; partner_name: string | null; confidence: number };
  'conv.intents': { trial_id: string; labels: string[] };
  'conv.candidates': { trial_id: string; candidates: string[]; grounding: string[] };
  'conv.spoken': {
    text: string
    voice: 'cache' | 'elevenlabs' | 'piper' | 'browser'
    cached: boolean
    latency_ms: number
    audio_b64?: string
    playback_id?: string
    playback_timeout_s?: number
  };
  'graph.snapshot': { nodes: GraphNode[]; edges: GraphEdge[] };
  'graph.activate': { node_ids: string[]; edge_ids: string[]; reason: string };
  'graph.bloom': { nodes: GraphNode[]; edges: GraphEdge[] };
  'fsm.state': { state: FsmState; detail: string };
  'sys.status': SysStatusPayload;
  'analytics.summary': AnalyticsSummary;
  'privacy.flow': { stage: string; destination: string; bytes: number; description: string };
  'privacy.cost': { turn_id: string; items: PrivacyCostItem[]; turn_usd: number; session_usd: number };
  'spectator.link': { url: string | null; connected_viewers: number };
}
export type FsmState = 'UNSEEDED' | 'IDLE' | 'TRANSCRIBING' | 'GROUNDING' | 'INTENT_GEN' | 'INTENT_WAIT' | 'CANDIDATE_GEN' | 'CANDIDATE_WAIT' | 'SPEAKING' | 'LEARNING';
export type WsType = keyof WsPayloads;
export type WsMessage = { [K in WsType]: { type: K; ts: number; payload: WsPayloads[K] } }[WsType];
export const HIGH_RATE: ReadonlySet<WsType> = new Set(['eeg.trace', 'eeg.psd', 'bci.scores']); // refs + rAF only, never useState (§16.3)
