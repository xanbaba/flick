"""Loader for config.yaml plus .env, per ARCHITECTURE.md section 5.

``config.yaml`` holds tunable, non-secret constants; secrets live in
``.env`` and are never written to config.yaml. Both are frozen
interfaces per AGENTS.md section 4.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_PATH = Path("config.yaml")


# --------------------------------------------------------------------------
# config.yaml models
# --------------------------------------------------------------------------


class InputConfig(BaseModel):
    adapter: Literal["keyboard", "ssvep", "replay", "emotiv"]
    replay_file: str | None


class ModeConfig(BaseModel):
    source: Literal["cyton", "synthetic", "replay"]
    targets: Literal[5, 4]


class EegConfig(BaseModel):
    board: str
    sample_rate: int
    channels: list[int]
    channel_names: list[str]
    serial_port: str


class DspConfig(BaseModel):
    hop_s: float
    notch_hz: float
    notch_q: float
    bandpass_high_hz: float
    bandpass_order: int


class StimulusProfileSpec(BaseModel):
    min_refresh_hz: float
    render: Literal["sinusoid", "divisor"]
    frequencies: list[float]
    phases: list[float]
    cancel_idx: int
    window_s: float
    bandpass_low_hz: float
    fbcca_subband_low_hz: list[float]


class StimulusProfiles(BaseModel):
    hi: StimulusProfileSpec
    lo: StimulusProfileSpec


class StimulusConfig(BaseModel):
    profile: Literal["auto", "hi", "lo"]
    tile_layout: str
    tile_px: int
    contrast: float
    cue_duration_s: float
    label_font_px: int
    integrity_drop_threshold: int
    profiles: StimulusProfiles


class FbccaConfig(BaseModel):
    n_subbands: int
    subband_high_hz: float
    weight_a: float
    weight_b: float


class EtrcaConfig(BaseModel):
    calibration_max_age_s: int
    model_dir: str


class ClassifyConfig(BaseModel):
    algorithm: Literal["auto", "fbcca", "etrca"]
    harmonics: int
    fbcca: FbccaConfig
    etrca: EtrcaConfig


class DecisionConfig(BaseModel):
    rho_threshold: float
    margin_ratio: float
    dwell_windows: int
    refractory_s: float


class CalibrationConfig(BaseModel):
    blocks: int
    trial_s: float
    rest_s: float


class GraphConfig(BaseModel):
    db_path: str
    embedding_dim: int


class RetrievalConfig(BaseModel):
    vector_top_k: int
    hops: int
    candidate_cap: int
    select_k: int


class GenerationConfig(BaseModel):
    n_intents: int
    n_candidates: int
    max_tokens: int
    timeout_s: float


class ExtractionConfig(BaseModel):
    enabled: bool
    confidence_threshold: float
    max_new_nodes_per_turn: int
    dedup_similarity: float


class ReinforcementConfig(BaseModel):
    edge_increment: float
    node_increment: float
    max_weight: float


class VoiceConfig(BaseModel):
    cache_first: bool
    cache_dir: str


class TelemetryConfig(BaseModel):
    enabled: bool
    queue_maxsize: int  # bounded; DROPS on overflow, never blocks
    flush_interval_ms: int
    flush_batch: int
    eeg_downsample: int
    compress_after: str


class SpectatorConfig(BaseModel):
    enabled: bool
    url: str
    throttle_hz: float
    send_raw_eeg: bool  # NEVER true
    send_graph_content: bool


class PriceTable(BaseModel):
    gemini_in_per_1k: float
    gemini_out_per_1k: float
    elevenlabs_per_1k_chars: float
    deepgram_per_minute: float


class PrivacyConfig(BaseModel):
    local_mode: bool
    show_costs: bool
    price_table: PriceTable


class RecordingConfig(BaseModel):
    enabled: bool
    dir: str


class AppConfig(BaseModel):
    input: InputConfig
    mode: ModeConfig
    eeg: EegConfig
    dsp: DspConfig
    stimulus: StimulusConfig
    classify: ClassifyConfig
    decision: DecisionConfig
    calibration: CalibrationConfig
    graph: GraphConfig
    retrieval: RetrievalConfig
    generation: GenerationConfig
    extraction: ExtractionConfig
    reinforcement: ReinforcementConfig
    voice: VoiceConfig
    telemetry: TelemetryConfig
    spectator: SpectatorConfig
    privacy: PrivacyConfig
    recording: RecordingConfig


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Read and validate config.yaml."""
    raw = yaml.safe_load(Path(path).read_text())
    return AppConfig.model_validate(raw)


# --------------------------------------------------------------------------
# .env models
# --------------------------------------------------------------------------


class EnvSettings(BaseSettings):
    """Every secret and provider-selection variable from .env.example."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = ""
    gemini_api_key: str = ""
    gemini_model: str = ""

    openai_compat_base_url: str = ""
    openai_compat_model: str = ""
    openai_compat_api_key: str = ""

    do_gradient_base_url: str = ""
    do_gradient_model: str = ""
    do_gradient_api_key: str = ""

    stt_provider: str = ""
    deepgram_api_key: str = ""

    tts_provider: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    piper_model_path: str = ""

    embedding_provider: str = ""

    timescale_dsn: str = ""

    spectator_url: str = ""
    spectator_token: str = ""

    emotiv_client_id: str = ""
    emotiv_client_secret: str = ""

    demo_replay: bool = False
    local_mode: bool = False

    @field_validator("demo_replay", "local_mode", mode="before")
    @classmethod
    def _blank_env_value_means_false(cls, value: object) -> object:
        """.env.example ships every variable empty (AGENTS.md non-negotiable #1).

        A plain `cp .env.example .env` must still boot: treat an unset
        boolean flag as False rather than failing validation on "".
        """
        if value == "":
            return False
        return value


class Settings(BaseModel):
    """Combined view of config.yaml and .env."""

    config: AppConfig
    env: EnvSettings


@lru_cache
def get_settings(config_path: Path | str = DEFAULT_CONFIG_PATH) -> Settings:
    """Load and cache the combined application settings."""
    return Settings(config=load_config(config_path), env=EnvSettings())
