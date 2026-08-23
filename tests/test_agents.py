from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tests.fakes import FakeLLMClient

from research_report_agent.agents.critic import Critic
from research_report_agent.agents.guardrail import FinalGuardrail, IntakeGuardrail
from research_report_agent.agents.planner import Planner
from research_report_agent.agents.synthesizer import Synthesizer, _ReportDraft
from research_report_agent.contracts import (
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
)


def worker_result(task_id: str = "task_001", status: str = "completed") -> WorkerResult:
    now = datetime.now(UTC)
    return WorkerResult(
        task_id=task_id,
        status=status,
        summary=f"{task_id} summary",
        findings=[
            Finding(
                finding_id=f"{task_id}_finding_001",
                claim=f"{task_id} supported claim",
                evidence="Independent evidence",
                source_ids=["src_001"],
                confidence=0.75,
            )
        ],
        sources=[
            Source(
                source_id="src_001",
                title="Example source",
                url="https://example.com/source",
                publisher="Example publisher",
                retrieved_at=now,
                credibility="medium-high",
            )
        ],
        gaps=[] if status == "completed" else ["More evidence required"],
    )


def research_plan() -> ResearchPlan:
    return ResearchPlan(
        plan_id="plan_001",
        objective="Compare EV battery chemistries",
        tasks=[
            ResearchTask(
                task_id="task_001",
                question="Identify the chemistries",
                success_criteria=["Names at least three chemistries"],
                required_tools=["web_search"],
                priority="high",
                dependencies=[],
            ),
            ResearchTask(
                task_id="task_002",
                question="Compare cost",
                success_criteria=["Covers cost"],
                required_tools=["web_search"],
                priority="high",
                dependencies=["task_001"],
            ),
            ResearchTask(
                task_id="task_003",
                question="Compare safety",
                success_criteria=["Covers safety"],
                required_tools=["web_search"],
                priority="high",
                dependencies=["task_001"],
            ),
        ],
    )


async def test_planner_returns_the_llm_validated_plan() -> None:
    plan = research_plan()
    llm = FakeLLMClient([plan])

    result = await Planner(llm).create_plan("Compare EV battery chemistries", ["cost", "safety"])

    assert result is plan
    assert llm.calls[0]["schema"] is ResearchPlan
    assert llm.calls[0]["max_repairs"] == 2
    assert "cost" in llm.calls[0]["user"]


async def test_intake_guardrail_passes_through_llm_verdict() -> None:
    review = GuardrailReview(
        guardrail_id="guardrail_intake_001",
        run_id="run_001",
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
    llm = FakeLLMClient([review])

    result = await IntakeGuardrail(llm).review("run_001", "Compare EV battery chemistries")

    assert result is review
    assert llm.calls[0]["schema"] is GuardrailReview
    assert "run_001" in llm.calls[0]["user"]


async def test_final_guardrail_passes_through_llm_verdict() -> None:
    review = GuardrailReview(
        guardrail_id="guardrail_final_001",
        run_id="run_001",
        mode=GuardrailMode.FINAL_OUTPUT,
        verdict=GuardrailVerdict.BLOCK,
        risk_level="critical",
        checks=[
            GuardrailCheck(
                check=GuardrailCheckType.HARMFUL_CONTENT, status=GuardrailCheckStatus.BLOCKED
            )
        ],
        blocked_reason="Report contains unsafe content",
    )
    llm = FakeLLMClient([review])

    result = await FinalGuardrail(llm).review_markdown("run_001", "# Report\n\nUnsafe content.")

    assert result is review
    assert llm.calls[0]["schema"] is GuardrailReview


async def test_critic_passes_through_llm_review() -> None:
    review = CriticReview(
        review_id="review_001",
        run_id="run_001",
        overall_verdict=CriticVerdict.ACCEPT,
        task_reviews=[
            CriticTaskReview(
                task_id="task_001", verdict=CriticVerdict.ACCEPT, reason="Well sourced"
            )
        ],
    )
    llm = FakeLLMClient([review])

    result = await Critic(llm).review("run_001", [worker_result()])

    assert result is review
    assert llm.calls[0]["schema"] is CriticReview


async def test_synthesizer_requires_evidence() -> None:
    with pytest.raises(ValueError, match="evidence"):
        await Synthesizer(FakeLLMClient([])).synthesize(
            run_id="run_001", goal="Compare technologies", results=[]
        )


def _draft(**overrides: object) -> _ReportDraft:
    payload = {
        "title": "EV Battery Comparison",
        "executive_summary": "Summary text.",
        "sections": [{"heading": "Cost", "markdown": "Cost details [1]."}],
        "comparison_table_markdown": None,
        "conclusions": [
            {
                "conclusion": "LFP and NMC trade cost for density.",
                "confidence": 0.7,
                "basis": ["placeholder_will_be_overridden"],
            }
        ],
        "limitations": ["Limited public data."],
    }
    payload.update(overrides)
    return _ReportDraft.model_validate(payload)


async def test_synthesizer_remaps_and_preserves_citations() -> None:
    result = worker_result()
    llm = FakeLLMClient([_draft()])

    document = await Synthesizer(llm).synthesize(
        run_id="run_001", goal="Compare technologies", results=[result]
    )

    assert document.markdown.startswith("#")
    assert document.structured["sources"]
    assert document.structured["citation_map"]
    accepted_ids = document.structured["accepted_finding_ids"]
    assert accepted_ids == ["task_001_task_001_finding_001"]
    assert document.structured["conclusions"][0]["basis"] == accepted_ids[:1]


async def test_synthesizer_strips_finding_id_leakage_from_prose() -> None:
    result = worker_result()
    leaked_id = "task_001_task_001_finding_001"  # the merged id for this fixture
    draft = _draft(
        executive_summary=f"LFP is cheaper [{leaked_id}], per the survey.",
        sections=[{"heading": "Cost", "markdown": f"Details (id: {leaked_id}) follow."}],
    )
    llm = FakeLLMClient([draft])

    document = await Synthesizer(llm).synthesize(
        run_id="run_001", goal="Compare technologies", results=[result]
    )

    assert leaked_id not in document.markdown
    assert leaked_id not in document.structured["executive_summary"]
    assert leaked_id not in document.structured["sections"][0]["markdown"]
    assert document.structured["executive_summary"] == "LFP is cheaper, per the survey."


async def test_synthesizer_deduplicates_sources_across_workers() -> None:
    llm = FakeLLMClient([_draft()])

    document = await Synthesizer(llm).synthesize(
        run_id="run_001",
        goal="Compare technologies",
        results=[worker_result(), worker_result("task_002")],
    )

    urls = [source["url"] for source in document.structured["sources"]]
    assert len(urls) == len(set(urls))


async def test_synthesizer_falls_back_when_llm_basis_is_invalid() -> None:
    draft = _draft(
        conclusions=[
            {"conclusion": "Bad basis.", "confidence": 0.5, "basis": ["nonexistent_finding"]}
        ]
    )
    llm = FakeLLMClient([draft])

    document = await Synthesizer(llm).synthesize(
        run_id="run_001",
        goal="Compare technologies",
        results=[worker_result()],
    )

    basis = document.structured["conclusions"][0]["basis"]
    assert basis == document.structured["accepted_finding_ids"][:1]


async def test_synthesizer_passes_dimensions_into_the_prompt() -> None:
    result = worker_result()
    llm = FakeLLMClient([_draft()])

    await Synthesizer(llm).synthesize(
        run_id="run_001",
        goal="Compare technologies",
        results=[result],
        dimensions=["cost", "risks"],
    )

    prompt = llm.calls[0]["user"]
    assert "Required dimensions" in prompt
    assert "cost" in prompt
    assert "risks" in prompt


async def test_synthesizer_omits_the_dimension_line_when_none_are_given() -> None:
    result = worker_result()
    llm = FakeLLMClient([_draft()])

    await Synthesizer(llm).synthesize(
        run_id="run_001", goal="Compare technologies", results=[result]
    )

    assert "Required dimensions" not in llm.calls[0]["user"]
