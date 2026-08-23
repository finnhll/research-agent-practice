"""Test double for LLMClient: replays a scripted queue of structured responses.

Keeps agent/worker/orchestrator tests fast, offline, and deterministic — the same
role a mocked HTTP transport plays for ``tools.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from research_report_agent.agents.synthesizer import _ReportDraft
from research_report_agent.contracts import (
    ClarifiedGoal,
    CriticReview,
    CriticTaskReview,
    CriticVerdict,
    Finding,
    GuardrailCheck,
    GuardrailCheckStatus,
    GuardrailCheckType,
    GuardrailMode,
    GuardrailReview,
    GuardrailVerdict,
    ResearchPlan,
    ResearchTask,
    Source,
    WorkerResult,
    WorkerStatus,
)


class FakeLLMClient:
    """Implements the same ``complete_structured`` interface as ``LLMClient``."""

    def __init__(self, responses: list[BaseModel | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_repairs: int = 1,
    ) -> BaseModel:
        self.calls.append(
            {"system": system, "user": user, "schema": schema, "max_repairs": max_repairs}
        )
        if not self._responses:
            raise AssertionError("FakeLLMClient has no more scripted responses")

        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if not isinstance(response, schema):
            raise AssertionError(
                f"FakeLLMClient scripted a {type(response).__name__} "
                f"but the caller requested {schema.__name__}"
            )
        return response

    async def list_model_ids(self) -> list[str]:
        return ["fake-model"]


class StubWorkerRuntime:
    """A worker runtime that never touches an LLM or the network.

    Used by orchestrator/API tests that exercise scheduling, persistence, and
    cancellation — not worker reasoning, which is covered by ``test_worker_runtime.py``.
    """

    def __init__(self, *, status: WorkerStatus = WorkerStatus.COMPLETED) -> None:
        self._status = status
        self.tools = SimpleNamespace(call_count=0)

    async def execute_attempt(self, request: Any, *, cancel_event: Any = None) -> WorkerResult:
        if self._status is not WorkerStatus.COMPLETED:
            return WorkerResult(
                task_id=request.task_id,
                status=self._status,
                summary="No usable evidence was found.",
                gaps=["No usable evidence was found."],
            )
        now = datetime.now(UTC)
        return WorkerResult(
            task_id=request.task_id,
            status=WorkerStatus.COMPLETED,
            summary=f"{request.task_id} summary",
            findings=[
                Finding(
                    finding_id="finding_001",
                    claim="Stub claim",
                    evidence="Stub evidence",
                    source_ids=["src_001"],
                    confidence=0.8,
                )
            ],
            sources=[
                Source(
                    source_id="src_001",
                    title="Stub source",
                    url=f"https://example.com/{request.task_id}",
                    publisher="Example",
                    retrieved_at=now,
                    credibility="medium-high",
                )
            ],
        )


def make_intake_review(*, allow: bool = True) -> GuardrailReview:
    if allow:
        return GuardrailReview(
            guardrail_id="guardrail_intake_001",
            run_id="run_pending",
            mode=GuardrailMode.INTAKE,
            verdict=GuardrailVerdict.ALLOW,
            risk_level="low",
            checks=[
                GuardrailCheck(
                    check=GuardrailCheckType.HARMFUL_CONTENT, status=GuardrailCheckStatus.PASS
                )
            ],
            reason="Benign research goal",
        )
    return GuardrailReview(
        guardrail_id="guardrail_intake_001",
        run_id="run_pending",
        mode=GuardrailMode.INTAKE,
        verdict=GuardrailVerdict.BLOCK,
        risk_level="high",
        checks=[
            GuardrailCheck(
                check=GuardrailCheckType.HARMFUL_CONTENT, status=GuardrailCheckStatus.BLOCKED
            )
        ],
        blocked_reason="This research goal is not allowed.",
    )


def make_final_review() -> GuardrailReview:
    return GuardrailReview(
        guardrail_id="guardrail_final_001",
        run_id="run_pending",
        mode=GuardrailMode.FINAL_OUTPUT,
        verdict=GuardrailVerdict.ALLOW,
        risk_level="low",
        checks=[
            GuardrailCheck(
                check=GuardrailCheckType.HARMFUL_CONTENT, status=GuardrailCheckStatus.PASS
            )
        ],
        reason="Safe report",
    )


def make_plan(task_ids: list[str]) -> ResearchPlan:
    tasks = [
        ResearchTask(
            task_id=task_ids[0],
            question="Identify the central entities",
            success_criteria=["Identify the relevant entities"],
            required_tools=["web_search"],
            priority="high",
            dependencies=[],
        )
    ]
    for task_id in task_ids[1:]:
        tasks.append(
            ResearchTask(
                task_id=task_id,
                question="Analyze a dimension",
                success_criteria=["Cover the dimension with evidence"],
                required_tools=["web_search"],
                priority="high",
                dependencies=[task_ids[0]],
            )
        )
    return ResearchPlan(plan_id="plan_001", objective="Stub objective", tasks=tasks)


def make_critic_review(task_ids: list[str], verdict: CriticVerdict) -> CriticReview:
    return CriticReview(
        review_id="review_001",
        run_id="run_pending",
        overall_verdict=verdict,
        task_reviews=[
            CriticTaskReview(task_id=task_id, verdict=verdict, reason="Stub review")
            for task_id in task_ids
        ],
    )


def make_report_draft() -> _ReportDraft:
    return _ReportDraft(
        title="Stub Report",
        executive_summary="Stub executive summary.",
        sections=[{"heading": "Findings", "markdown": "Stub findings [1]."}],
        comparison_table_markdown=None,
        conclusions=[
            {"conclusion": "Stub conclusion.", "confidence": 0.7, "basis": ["placeholder"]}
        ],
        limitations=["Stub limitation."],
    )


def make_clarified_goal(goal: str = "Compare technologies") -> ClarifiedGoal:
    """The clarifier response every factory scripts between intake and planning."""
    return ClarifiedGoal(
        intent="comparison",
        rewritten_goal=goal,
        rationale="The question was already specific enough to research as written.",
        assumptions=[],
        suggested_dimensions=[],
    )


def happy_path_llm_factory(task_ids: list[str]):
    """A ``llm_factory`` that scripts a full ALLOW -> plan -> accept -> report -> ALLOW run."""

    def factory() -> FakeLLMClient:
        accept = make_critic_review(task_ids, CriticVerdict.ACCEPT)
        return FakeLLMClient(
            [
                make_intake_review(allow=True),
                make_clarified_goal(),
                make_plan(task_ids),
                accept,
                accept,
                make_report_draft(),
                make_final_review(),
            ]
        )

    return factory


def failing_llm_factory(task_ids: list[str]):
    """A ``llm_factory`` that scripts a plan whose critic finds no usable evidence."""

    def factory() -> FakeLLMClient:
        fail = make_critic_review(task_ids, CriticVerdict.FAIL)
        return FakeLLMClient(
            [
                make_intake_review(allow=True),
                make_clarified_goal(),
                make_plan(task_ids),
                fail,
                fail,
            ]
        )

    return factory


def blocked_llm_factory():
    """A ``llm_factory`` that scripts an intake guardrail block."""

    def factory() -> FakeLLMClient:
        return FakeLLMClient([make_intake_review(allow=False)])

    return factory


def planning_only_llm_factory(task_ids: list[str]):
    """A ``llm_factory`` that scripts only intake + planning, for tests that cancel mid-run."""

    def factory() -> FakeLLMClient:
        return FakeLLMClient(
            [make_intake_review(allow=True), make_clarified_goal(), make_plan(task_ids)]
        )

    return factory


__all__ = [
    "FakeLLMClient",
    "StubWorkerRuntime",
    "blocked_llm_factory",
    "failing_llm_factory",
    "happy_path_llm_factory",
    "make_clarified_goal",
    "make_critic_review",
    "make_final_review",
    "make_intake_review",
    "make_plan",
    "make_report_draft",
    "planning_only_llm_factory",
]
