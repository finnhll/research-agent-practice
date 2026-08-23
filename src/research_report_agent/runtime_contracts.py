"""Runtime contracts for orchestration, tools, attempts, and API events."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from research_report_agent.contracts import ResearchTask, WorkerResult


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class RunPhase(StrEnum):
    """coarse graph phase exposed to the API."""

    CREATED = "created"
    INTAKE_GUARDRAIL = "intake_guardrail"
    CLARIFYING = "clarifying"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    PLANNING = "planning"
    PLAN_REPAIR = "plan_repair"
    SCHEDULING = "scheduling"
    EXECUTING = "executing"
    WORKER_REPAIR = "worker_repair"
    REVIEWING = "reviewing"
    REVISING = "revising"
    REPLANNING = "replanning"
    SYNTHESIZING = "synthesizing"
    REPORT_REPAIR = "report_repair"
    FINAL_GUARDRAIL = "final_guardrail"
    FINALIZING = "finalizing"
    TERMINAL = "terminal"


class RunStatus(StrEnum):
    """Terminal or running status of a research run."""

    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    COMPLETE = "complete"
    COMPLETE_WITH_CAVEATS = "complete_with_caveats"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskState(StrEnum):
    """Scheduling state of one planned task."""

    PENDING = "pending"
    BLOCKED = "blocked"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class AttemptKind(StrEnum):
    """Why a worker attempt was dispatched."""

    INITIAL = "initial"
    RETRY = "retry"
    CRITIC_REVISION = "critic_revision"
    REPLAN = "replan"


class ToolName(StrEnum):
    """Tools available to worker agents."""

    WEB_SEARCH = "web_search"
    FETCH_PAGE = "fetch_page"
    CALCULATOR = "calculator"


class ToolStatus(StrEnum):
    """Execution result of one tool call."""

    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"


class StrictRuntimeModel(BaseModel):
    """Runtime model that rejects undeclared fields."""

    model_config = ConfigDict(extra="forbid")


class RunBudget(StrictRuntimeModel):
    """Bounded execution policy for a run or worker attempt."""

    max_parallel_workers: int = Field(default=3, gt=0)
    max_reasoning_steps: int = Field(default=10, gt=0)
    max_tool_calls_per_attempt: int = Field(default=6, gt=0)
    # A worker attempt can chain up to max_tool_calls_per_attempt tool calls, each
    # preceded by an LLM call to choose the action, plus one final extraction call —
    # against real network I/O this is measured to regularly exceed 90s (the original
    # estimate from docs/spec/design.md before this ran against a real model/network).
    attempt_timeout_seconds: float = Field(default=240, gt=0)
    max_retries_per_task: int = Field(default=1, ge=0)
    max_replans: int = Field(default=1, ge=0)


class RunUsage(StrictRuntimeModel):
    """Observable resource usage for a run."""

    llm_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    search_calls: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)
    replans: int = Field(default=0, ge=0)


class RunMode(StrEnum):
    """How much the user wants to be asked before the agent proceeds."""

    AUTONOMOUS = "autonomous"
    GUIDED = "guided"


class PendingGate(StrictRuntimeModel):
    """A checkpoint the run is parked on, waiting for a human answer.

    Stored on the run rather than in a checkpointer: everything the graph needs
    to resume already lives in the domain tables, so this only has to carry what
    the user is being asked.
    """

    kind: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class RunRecord(StrictRuntimeModel):
    """Persisted top-level state for one research run."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    run_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    phase: RunPhase = RunPhase.CREATED
    status: RunStatus = RunStatus.RUNNING
    budget: RunBudget = Field(default_factory=RunBudget)
    usage: RunUsage = Field(default_factory=RunUsage)
    mode: RunMode = RunMode.AUTONOMOUS
    pending_gate: PendingGate | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    error: str | None = None


class WorkerAttemptRequest(StrictRuntimeModel):
    """Input to exactly one worker attempt."""

    run_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    task_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    attempt_kind: AttemptKind = AttemptKind.INITIAL
    question: str = Field(min_length=1)
    success_criteria: list[str] = Field(min_length=1)
    allowed_tools: list[ToolName] = Field(min_length=1)
    upstream_context: dict[str, Any] = Field(default_factory=dict)
    limits: RunBudget = Field(default_factory=RunBudget)

    @field_validator("allowed_tools")
    @classmethod
    def reject_duplicate_tools(cls, value: list[ToolName]) -> list[ToolName]:
        if len(value) != len(set(value)):
            raise ValueError("allowed_tools must be unique")
        return value


class WorkerAttempt(StrictRuntimeModel):
    """Persisted metadata about one immutable worker attempt."""

    run_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    task_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    attempt_kind: AttemptKind = AttemptKind.INITIAL
    state: TaskState
    started_at: datetime
    completed_at: datetime | None = None
    result: WorkerResult | None = None
    error: str | None = None


class ToolRequest(StrictRuntimeModel):
    """Typed request from a worker to the tool layer."""

    request_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    tool: str
    input: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)


class ToolResult(StrictRuntimeModel):
    """Sanitized result returned by the tool layer."""

    request_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    tool: str
    status: ToolStatus
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime = Field(default_factory=utc_now)


class AgentEvent(StrictRuntimeModel):
    """Append-only event exposed by the API and SSE stream."""

    event_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=utc_now)
    task_id: str | None = None
    attempt_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class PlannedTaskRecord(StrictRuntimeModel):
    """Persisted planning and scheduling state for one task."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    run_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    task: ResearchTask
    state: TaskState = TaskState.PENDING
    attempt_count: int = Field(default=0, ge=0)
    produced_context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReportDocument(StrictRuntimeModel):
    """Final report plus rendered Markdown and guardrail outcome."""

    report_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    markdown: str = Field(min_length=1)
    structured: dict[str, Any]
    guardrail_verdict: Literal["allow", "revise", "block"]
    created_at: datetime = Field(default_factory=utc_now)


__all__ = [
    "AgentEvent",
    "AttemptKind",
    "PlannedTaskRecord",
    "ReportDocument",
    "RunRecord",
    "RunBudget",
    "RunPhase",
    "RunStatus",
    "RunUsage",
    "TaskState",
    "ToolName",
    "ToolRequest",
    "ToolResult",
    "WorkerAttempt",
    "WorkerAttemptRequest",
    "utc_now",
]
