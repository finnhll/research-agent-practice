from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from research_report_agent.runtime_contracts import (
    AgentEvent,
    RunBudget,
    RunPhase,
    RunStatus,
    TaskState,
    ToolRequest,
    ToolResult,
    WorkerAttempt,
    WorkerAttemptRequest,
)


def test_runtime_states_are_explicit() -> None:
    assert RunPhase.EXECUTING.value == "executing"
    assert RunStatus.COMPLETE_WITH_CAVEATS.value == "complete_with_caveats"
    assert TaskState.READY.value == "ready"


def test_budget_rejects_non_positive_limits() -> None:
    with pytest.raises(ValidationError):
        RunBudget(max_parallel_workers=0)


def test_worker_attempt_request_binds_attempt_identity() -> None:
    request = WorkerAttemptRequest(
        run_id="run_001",
        plan_id="plan_001",
        plan_version=1,
        task_id="task_001",
        attempt_id="task_001_attempt_001",
        question="Identify relevant technologies.",
        success_criteria=["Identify at least three technologies"],
        allowed_tools=["web_search"],
        upstream_context={"selected_entities": ["LFP"]},
        limits=RunBudget(),
    )
    attempt = WorkerAttempt(
        run_id=request.run_id,
        plan_id=request.plan_id,
        plan_version=request.plan_version,
        task_id=request.task_id,
        attempt_id=request.attempt_id,
        state=TaskState.RUNNING,
        started_at=datetime.now(UTC),
    )

    assert request.attempt_id == attempt.attempt_id
    assert attempt.state is TaskState.RUNNING


def test_tool_round_trip_is_structured() -> None:
    request = ToolRequest(
        request_id="tool_req_001",
        attempt_id="task_001_attempt_001",
        tool="calculator",
        input={"expression": "2 + 2"},
    )
    result = ToolResult(
        request_id=request.request_id,
        attempt_id=request.attempt_id,
        tool=request.tool,
        status="success",
        output={"value": 4},
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )

    assert result.output == {"value": 4}


def test_agent_event_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AgentEvent(
            event_id="event_001",
            run_id="run_001",
            event_type="run.created",
            timestamp=datetime.now(UTC),
            data={},
            unexpected=True,
        )
