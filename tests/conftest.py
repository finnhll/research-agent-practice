"""Shared test fixtures.

Isolates every test from the real (gitignored) ``model-config.json`` that a developer
running this repo locally may have — no test should ever read or write it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_report_agent import config


@pytest.fixture(autouse=True)
def _isolated_model_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_CONFIG_PATH", tmp_path / "model-config.json")
