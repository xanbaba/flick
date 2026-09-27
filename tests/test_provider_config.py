from pathlib import Path

import pytest

from shared.config import EnvSettings, GenerationConfig, load_config


def test_retry_defaults_match_yaml_without_changing_limits() -> None:
    config = load_config()
    defaults = GenerationConfig(n_intents=4, n_candidates=3, max_tokens=2048, timeout_s=12)
    assert config.generation == defaults
    assert config.generation.transient_retries == 1
    assert config.generation.retry_delay_s == 0.5
    assert config.generation.retry_jitter_s == 0.25
    assert config.generation.min_attempt_budget_s == 2
    assert "local_mode" not in config.privacy.model_dump()


def test_legacy_local_mode_environment_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_MODE", "true")
    assert "local_mode" not in EnvSettings(_env_file=None).model_dump()
    assert "LOCAL_MODE" not in Path(".env.example").read_text()
