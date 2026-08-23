"""Research & Report Agent package."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from research_report_agent.contracts import (
    CriticReview,
    GuardrailReview,
    ResearchPlan,
    ResearchReport,
    WorkerResult,
)

try:
    # pyproject.toml is the single source of truth; deriving it here keeps the
    # API's OpenAPI version and the outbound User-Agent from drifting apart.
    __version__ = _version("research-report-agent")
except PackageNotFoundError:  # pragma: no cover - source tree without metadata
    __version__ = "0.0.0+unknown"

__all__ = [
    "CriticReview",
    "GuardrailReview",
    "ResearchPlan",
    "ResearchReport",
    "WorkerResult",
    "__version__",
]
