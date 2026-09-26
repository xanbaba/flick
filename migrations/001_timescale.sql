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
