"""Typed contracts for messages exchanged between agents.

These models are the executable version of the JSON contracts in
``docs/spec/design.md``. Every model boundary should validate agent output before
the graph is allowed to continue.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _require_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must include a timezone")
    return value.astimezone(UTC)


class WorkerStatus(StrEnum):
    """Execution outcome for one research worker."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"
    BLOCKED = "blocked"


class StrictModel(BaseModel):
    """Base model that rejects undeclared fields at agent boundaries."""

    model_config = ConfigDict(extra="forbid")


class CriticVerdict(StrEnum):
    """Quality-review action requested by the critic."""

    ACCEPT = "accept"
    REVISE = "revise"
    REPLAN = "replan"
    DEGRADE = "degrade"
    FAIL = "fail"


class GuardrailMode(StrEnum):
    """Where in the graph the guardrail is applied."""

    INTAKE = "intake"
    FINAL_OUTPUT = "final_output"


class GuardrailVerdict(StrEnum):
    """Safety-review action requested by the guardrail."""

    ALLOW = "allow"
    REVISE = "revise"
    BLOCK = "block"
    ESCALATE = "escalate"


class GuardrailCheckType(StrEnum):
    """Safety and policy checks used by the guardrail."""

    HARMFUL_CONTENT = "harmful_content"
    PRIVACY = "privacy"
    HARASSMENT = "harassment"
    ILLEGAL_ACTIVITY = "illegal_activity"
    HIGH_RISK_ADVICE = "high_risk_advice"
    INSTRUCTION_OVERRIDE = "instruction_override"
    PROMPT_INJECTION_LEAKAGE = "prompt_injection_leakage"
    CITATION_RISK = "citation_risk"
    CONFIDENCE_RISK = "confidence_risk"


class GuardrailCheckStatus(StrEnum):
    """Result of one guardrail check."""

    PASS = "pass"
    FLAGGED = "flagged"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class ClarifiedGoal(StrictModel):
    """The clarifier's reading of a research question, shown to the user for confirmation.

    This exists so a misread question is caught before any research is paid for --
    the only gate in the system that happens before spend rather than after it.
    """

    intent: str = Field(min_length=1)
    rewritten_goal: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    suggested_dimensions: list[str] = Field(default_factory=list, max_length=2)


class ResearchTask(StrictModel):
    """One bounded unit of research produced by the planner."""

    task_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    success_criteria: list[str] = Field(min_length=1)
    required_tools: list[str] = Field(min_length=1)
    priority: Literal["low", "medium", "high"]
    dependencies: list[str] = Field(default_factory=list)

    @field_validator("dependencies")
    @classmethod
    def reject_duplicate_dependencies(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("dependencies must be unique")
        return value


class ResearchPlan(StrictModel):
    """A validated plan containing three to six acyclic research tasks."""

    plan_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    tasks: list[ResearchTask]

    @model_validator(mode="after")
    def validate_task_graph(self) -> ResearchPlan:
        if not 3 <= len(self.tasks) <= 6:
            raise ValueError("tasks must contain between 3 and 6 items")

        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task_id values must be unique")

        graph = {task.task_id: set(task.dependencies) for task in self.tasks}
        for task_id, dependencies in graph.items():
            if task_id in dependencies:
                raise ValueError(f"task {task_id} cannot depend on itself")
            unknown = dependencies.difference(graph)
            if unknown:
                raise ValueError(f"unknown dependencies for {task_id}: {sorted(unknown)}")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visited:
                return
            if node in visiting:
                raise ValueError("plan contains a circular dependency")

            visiting.add(node)
            for dependency in graph[node]:
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for task_id in graph:
            visit(task_id)

        return self


class Source(StrictModel):
    """A source referenced by one or more findings."""

    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")
    publisher: str = Field(min_length=1)
    published_at: datetime | None = None
    retrieved_at: datetime
    credibility: Literal["low", "medium", "medium-high", "high"]
    notes: str | None = None

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        return _require_utc_datetime(value) if value is not None else None


class Finding(StrictModel):
    """A sourced research claim returned by a worker."""

    finding_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("source_ids")
    @classmethod
    def reject_duplicate_sources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("source_ids must be unique")
        return value


class WorkerResult(StrictModel):
    """Structured output from one worker agent."""

    task_id: str = Field(min_length=1)
    status: WorkerStatus
    summary: str = Field(min_length=1)
    findings: list[Finding] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    tool_trace_ref: str | None = None
    produced_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source_references(self) -> WorkerResult:
        source_ids = {source.source_id for source in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("source_id values must be unique")

        for finding in self.findings:
            missing = set(finding.source_ids).difference(source_ids)
            if missing:
                raise ValueError(
                    f"finding {finding.finding_id} references missing sources: {sorted(missing)}"
                )

        return self


class FollowUpTask(StrictModel):
    """A bounded follow-up generated by the critic."""

    task_id: str = Field(min_length=1)
    parent_task_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    constraints: list[str] = Field(min_length=1)
    max_tool_calls: int = Field(gt=0)


class CriticTaskReview(StrictModel):
    """Critic decision for one worker result."""

    task_id: str = Field(min_length=1)
    verdict: CriticVerdict
    reason: str = Field(min_length=1)
    follow_up: FollowUpTask | None = None

    @model_validator(mode="after")
    def require_follow_up_for_revision(self) -> CriticTaskReview:
        if self.verdict is CriticVerdict.REVISE and self.follow_up is None:
            raise ValueError("revise verdicts require follow_up")
        if self.verdict is not CriticVerdict.REVISE and self.follow_up is not None:
            raise ValueError("follow_up is only allowed for revise verdicts")
        return self


class CrossTaskIssue(StrictModel):
    """An issue that spans multiple worker results."""

    issue: str = Field(min_length=1)
    affected_task_ids: list[str] = Field(min_length=1)
    severity: Literal["low", "medium", "high"]
    recommended_action: CriticVerdict

    @field_validator("affected_task_ids")
    @classmethod
    def reject_duplicate_tasks(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("affected_task_ids must be unique")
        return value


class CriticReview(StrictModel):
    """Quality review across all worker outputs."""

    review_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    overall_verdict: CriticVerdict
    task_reviews: list[CriticTaskReview] = Field(min_length=1)
    cross_task_issues: list[CrossTaskIssue] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)


class GuardrailCheck(StrictModel):
    """One result in a guardrail review."""

    check: GuardrailCheckType
    status: GuardrailCheckStatus
    reason: str | None = None
    location: str | None = None


class GuardrailReview(StrictModel):
    """Intake or final-output safety decision."""

    guardrail_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    mode: GuardrailMode
    verdict: GuardrailVerdict
    risk_level: Literal["low", "medium", "high", "critical"]
    checks: list[GuardrailCheck]
    reason: str | None = None
    conditions: list[str] = Field(default_factory=list)
    revision_instructions: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None

    @model_validator(mode="after")
    def validate_verdict_requirements(self) -> GuardrailReview:
        if self.verdict is GuardrailVerdict.BLOCK and not self.blocked_reason:
            raise ValueError("block verdicts require blocked_reason")
        if self.verdict is GuardrailVerdict.REVISE and not self.revision_instructions:
            raise ValueError("revise verdicts require revision_instructions")
        return self


class ReportSection(StrictModel):
    """One rendered section of the final report."""

    heading: str = Field(min_length=1)
    markdown: str = Field(min_length=1)


class ReportConclusion(StrictModel):
    """One conclusion grounded in accepted findings."""

    conclusion: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    basis: list[str] = Field(min_length=1)

    @field_validator("basis")
    @classmethod
    def reject_duplicate_basis(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("basis finding IDs must be unique")
        return value


class ResearchReport(StrictModel):
    """Final structured report produced by the synthesizer."""

    report_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    sections: list[ReportSection] = Field(min_length=1)
    comparison_table_markdown: str | None = None
    conclusions: list[ReportConclusion] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)
    accepted_finding_ids: list[str] = Field(min_length=1)
    sources: list[Source] = Field(min_length=1)
    citation_map: Mapping[str, str]

    @model_validator(mode="after")
    def validate_citations_and_conclusions(self) -> ResearchReport:
        if len(self.accepted_finding_ids) != len(set(self.accepted_finding_ids)):
            raise ValueError("accepted_finding_ids must be unique")

        source_ids = {source.source_id for source in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("source_id values must be unique")

        missing_citations = set(self.citation_map.values()).difference(source_ids)
        if missing_citations:
            raise ValueError(
                f"citation map references missing sources: {sorted(missing_citations)}"
            )

        accepted = set(self.accepted_finding_ids)
        for conclusion in self.conclusions:
            missing = set(conclusion.basis).difference(accepted)
            if missing:
                raise ValueError(
                    f"conclusion uses findings absent from accepted_finding_ids: {sorted(missing)}"
                )

        return self


__all__ = [
    "CriticReview",
    "CriticTaskReview",
    "CriticVerdict",
    "CrossTaskIssue",
    "Finding",
    "FollowUpTask",
    "GuardrailCheck",
    "GuardrailCheckStatus",
    "GuardrailCheckType",
    "GuardrailMode",
    "GuardrailReview",
    "GuardrailVerdict",
    "ReportConclusion",
    "ReportSection",
    "ResearchPlan",
    "ResearchReport",
    "ResearchTask",
    "Source",
    "StrictModel",
    "WorkerResult",
    "WorkerStatus",
]
