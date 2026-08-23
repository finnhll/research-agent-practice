from __future__ import annotations

from pathlib import Path

import pytest

from research_report_agent import config


@pytest.fixture(autouse=True)
def isolated_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_CONFIG_PATH", tmp_path / "model-config.json")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_PROVIDER", raising=False)


def test_load_config_defaults_without_file_or_env() -> None:
    loaded = config.load_config()

    assert loaded.provider == "openai"
    assert loaded.model == "gpt-4o-mini"
    assert loaded.base_url is None
    assert loaded.api_key is None


def test_deepseek_provider_gets_preset_base_url_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_PROVIDER", "deepseek")

    loaded = config.load_config()

    assert loaded.provider == "deepseek"
    assert loaded.model == "deepseek-v4-flash"
    assert loaded.base_url == "https://api.deepseek.com"


def test_anthropic_provider_reads_its_own_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-be-used")

    loaded = config.load_config()

    assert loaded.provider == "anthropic"
    assert loaded.api_key == "anthropic-key"
    assert loaded.model == "claude-opus-5"


def test_unknown_provider_in_file_falls_back_to_openai() -> None:
    config.save_config(provider="not-a-real-provider", model="m", api_key="k")

    loaded = config.load_config()

    assert loaded.provider == "openai"


def test_env_vars_are_used_when_no_file_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("AGENT_MODEL", "env-model")

    loaded = config.load_config()

    assert loaded.model == "env-model"
    assert loaded.api_key == "env-key"


def test_saved_file_overrides_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    config.save_config(model="file-model", api_key="file-key")

    loaded = config.load_config()

    assert loaded.model == "file-model"
    assert loaded.api_key == "file-key"


def test_save_config_without_api_key_keeps_existing_key() -> None:
    config.save_config(model="model-a", api_key="secret")

    config.save_config(model="model-b")

    loaded = config.load_config()
    assert loaded.model == "model-b"
    assert loaded.api_key == "secret"


def test_mask_key_short_and_long() -> None:
    assert config.mask_key(None) is None
    assert config.mask_key("short") == "••••••••"
    assert config.mask_key("sk-1234567890") == "sk-12…7890"


def test_get_config_info_reports_key_source() -> None:
    config.save_config(model="model-a", api_key="secret")

    info = config.get_config_info()

    assert info.key_source == "file"
    assert info.api_key_masked is not None
