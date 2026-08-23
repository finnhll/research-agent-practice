"""Tests for the Python package scaffold."""

import tomllib
from pathlib import Path

import research_report_agent
from research_report_agent.tools import _USER_AGENT


def _pyproject_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    return str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])


def test_package_version_is_defined() -> None:
    assert research_report_agent.__version__


def test_package_version_matches_pyproject() -> None:
    """pyproject.toml is the single source of truth.

    The version used to be hardcoded separately in __init__, the FastAPI app,
    and the outbound User-Agent, and they drifted apart on the 0.2.0 bump.
    """
    assert research_report_agent.__version__ == _pyproject_version()


def test_user_agent_carries_the_real_version() -> None:
    assert f"research-report-agent/{research_report_agent.__version__}" in _USER_AGENT
    assert "github.com/finnhll/research-agent-practice" in _USER_AGENT
