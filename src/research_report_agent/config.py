"""Model API configuration: file-backed with environment variable fallback.

Mirrors the sibling ``sentinel`` project's ``src/config.ts`` so both products in this
workspace behave the same way: settings saved through the web UI are persisted to a
gitignored ``model-config.json`` and take priority over environment variables, so the
raw key is never round-tripped through the browser after it is first saved.

Three providers are supported out of the box (OpenAI, DeepSeek, Anthropic); any other
OpenAI-compatible gateway still works by picking "openai" as the provider and setting a
custom ``base_url``, exactly as before this file grew provider awareness.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel

_CONFIG_PATH = Path(os.getenv("RESEARCH_REPORT_AGENT_CONFIG", "model-config.json"))

Provider = Literal["openai", "deepseek", "anthropic"]


class ProviderPreset(TypedDict):
    label: str
    base_url: str | None
    models: list[str]


PROVIDER_PRESETS: dict[Provider, ProviderPreset] = {
    "openai": {
        "label": "OpenAI",
        "base_url": None,
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1"],
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
    },
    "anthropic": {
        "label": "Anthropic",
        "base_url": None,
        "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
    },
}


class ModelConfig(BaseModel):
    """Effective model configuration used to build an LLM client."""

    provider: Provider = "openai"
    model: str = "gpt-4o-mini"
    base_url: str | None = None
    api_key: str | None = None


class ModelConfigInfo(BaseModel):
    """UI-safe view of the configuration: the raw key is never exposed."""

    provider: Provider
    model: str
    base_url: str | None
    api_key_masked: str | None
    key_source: str | None


def _read_file() -> dict[str, Any]:
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _provider_api_key_env(provider: Provider) -> str | None:
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_API_KEY")
    return os.getenv("OPENAI_API_KEY")


def _provider_base_url_env(provider: Provider) -> str | None:
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_BASE_URL")
    return os.getenv("OPENAI_BASE_URL")


def load_config() -> ModelConfig:
    """Effective config: file values override environment variables."""

    file = _read_file()
    provider: Provider = file.get("provider") or os.getenv("AGENT_PROVIDER") or "openai"
    if provider not in PROVIDER_PRESETS:
        provider = "openai"
    preset = PROVIDER_PRESETS[provider]

    return ModelConfig(
        provider=provider,
        model=file.get("model") or os.getenv("AGENT_MODEL") or preset["models"][0],
        base_url=file.get("base_url") or _provider_base_url_env(provider) or preset["base_url"],
        api_key=file.get("api_key") or _provider_api_key_env(provider) or None,
    )


def save_config(
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> None:
    """Persist updates. An empty api_key means "keep the existing key"."""

    file = _read_file()
    if provider:
        file["provider"] = provider
    if model:
        file["model"] = model
    if base_url is not None:
        if base_url:
            file["base_url"] = base_url
        else:
            file.pop("base_url", None)
    if api_key:
        file["api_key"] = api_key
    _CONFIG_PATH.write_text(json.dumps(file, indent=2) + "\n")


def mask_key(key: str | None) -> str | None:
    if not key:
        return None
    if len(key) <= 8:
        return "••••••••"
    return f"{key[:5]}…{key[-4:]}"


def get_config_info() -> ModelConfigInfo:
    file = _read_file()
    config = load_config()
    return ModelConfigInfo(
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        api_key_masked=mask_key(config.api_key),
        key_source="file" if file.get("api_key") else ("env" if config.api_key else None),
    )


__all__ = [
    "PROVIDER_PRESETS",
    "ModelConfig",
    "ModelConfigInfo",
    "Provider",
    "ProviderPreset",
    "get_config_info",
    "load_config",
    "mask_key",
    "save_config",
]
