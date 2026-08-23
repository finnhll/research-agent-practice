from __future__ import annotations

import asyncio

from tests.fakes import FakeLLMClient

from research_report_agent.llm import LLMError
from research_report_agent.runtime_contracts import (
    RunBudget,
    ToolRequest,
    ToolResult,
    WorkerAttemptRequest,
)
from research_report_agent.worker_runtime import EvidenceExtraction, WorkerAction, WorkerRuntime


class _QueueToolExecutor:
    """Returns scripted ToolResults in order, ignoring the request's contents."""

    def __init__(self, results: list[ToolResult]) -> None:
        self._results = list(results)
        self.call_count = 0

    async def execute(self, _request: ToolRequest) -> ToolResult:
        self.call_count += 1
        return self._results.pop(0)


def request(
    *,
    question: str = "Compare EV battery chemistries for cost and safety",
    allowed_tools: list[str] | None = None,
    limits: RunBudget | None = None,
) -> WorkerAttemptRequest:
    return WorkerAttemptRequest(
        run_id="run_001",
        plan_id="plan_001",
        plan_version=1,
        task_id="task_001",
        attempt_id="task_001_attempt_001",
        question=question,
        success_criteria=["Find at least two sources"],
        allowed_tools=allowed_tools or ["web_search", "fetch_page"],
        limits=limits or RunBudget(max_tool_calls_per_attempt=3),
    )


def tool_result(tool: str, output: dict, *, status: str = "success") -> ToolResult:
    return ToolResult(
        request_id="tool_req_001",
        attempt_id="task_001_attempt_001",
        tool=tool,
        status=status,
        output=output,
    )


async def test_worker_respects_tool_allowlist() -> None:
    runtime = WorkerRuntime(FakeLLMClient([]))

    result = await runtime.execute_attempt(request(allowed_tools=["calculator"]))

    assert result.status.value == "blocked"
    assert "web_search" in result.gaps[0]


async def test_worker_supports_cancellation() -> None:
    runtime = WorkerRuntime(FakeLLMClient([]))
    cancelled = asyncio.Event()
    cancelled.set()

    result = await runtime.execute_attempt(request(), cancel_event=cancelled)

    assert result.status.value == "failed"


async def test_worker_returns_partial_when_it_finishes_without_tool_calls() -> None:
    llm = FakeLLMClient([WorkerAction(action="finish", reason="Nothing to research")])
    runtime = WorkerRuntime(llm, _QueueToolExecutor([]))

    result = await runtime.execute_attempt(request())

    assert result.status.value == "partial"
    assert result.gaps


async def test_worker_completes_with_sourced_findings() -> None:
    search_output = {
        "query": "EV battery chemistries",
        "results": [
            {
                "title": "Overview",
                "url": "https://a.example.com/overview",
                "publisher": "a.example.com",
                "snippet": "...",
            },
            {
                "title": "Cost survey",
                "url": "https://b.example.com/costs",
                "publisher": "b.example.com",
                "snippet": "...",
            },
        ],
    }
    llm = FakeLLMClient(
        [
            WorkerAction(
                action="web_search", input={"query": "EV battery chemistries"}, reason="search"
            ),
            WorkerAction(action="finish", reason="enough evidence"),
            EvidenceExtraction(
                summary="Found sourced evidence.",
                sources=[
                    {
                        "url": "https://a.example.com/overview",
                        "title": "Overview",
                        "publisher": "a.example.com",
                    },
                    {
                        "url": "https://b.example.com/costs",
                        "title": "Cost survey",
                        "publisher": "b.example.com",
                    },
                ],
                findings=[
                    {
                        "claim": "LFP is cheaper than NMC",
                        "evidence": "LFP packs are generally less expensive per kWh",
                        "source_urls": [
                            "https://a.example.com/overview",
                            "https://b.example.com/costs",
                        ],
                        "confidence": 0.8,
                    }
                ],
            ),
        ]
    )
    tools = _QueueToolExecutor([tool_result("web_search", search_output)])

    result = await WorkerRuntime(llm, tools).execute_attempt(request())

    assert result.status.value == "completed"
    assert len(result.sources) == 2
    assert result.findings and result.findings[0].source_ids == [
        result.sources[0].source_id,
        result.sources[1].source_id,
    ]
    assert result.produced_context == {"selected_entities": [], "covered_dimensions": []}


async def test_worker_enforces_tool_call_limit() -> None:
    search_output = {
        "query": "q",
        "results": [{"title": "T", "url": "https://a.example.com/x", "publisher": "a"}],
    }
    llm = FakeLLMClient(
        [
            WorkerAction(action="web_search", input={"query": "q"}, reason="search"),
            EvidenceExtraction(
                summary="Partial evidence.", sources=[], findings=[], gaps=["only one source"]
            ),
        ]
    )
    tools = _QueueToolExecutor([tool_result("web_search", search_output)])

    result = await WorkerRuntime(llm, tools).execute_attempt(
        request(limits=RunBudget(max_tool_calls_per_attempt=1))
    )

    assert tools.call_count == 1
    assert result.status.value == "partial"


async def test_worker_ignores_disallowed_tool_choice() -> None:
    llm = FakeLLMClient(
        [
            WorkerAction(
                action="fetch_page", input={"url": "https://a.example.com"}, reason="not allowed"
            ),
            WorkerAction(action="finish", reason="give up"),
        ]
    )
    tools = _QueueToolExecutor([])

    result = await WorkerRuntime(llm, tools).execute_attempt(request(allowed_tools=["web_search"]))

    assert tools.call_count == 0
    assert result.status.value == "partial"


async def test_worker_fails_when_evidence_extraction_errors() -> None:
    search_output = {
        "query": "q",
        "results": [{"title": "T", "url": "https://a.example.com/x", "publisher": "a"}],
    }
    llm = FakeLLMClient(
        [
            WorkerAction(action="web_search", input={"query": "q"}, reason="search"),
            WorkerAction(action="finish", reason="done"),
            LLMError("extraction failed"),
        ]
    )
    tools = _QueueToolExecutor([tool_result("web_search", search_output)])

    result = await WorkerRuntime(llm, tools).execute_attempt(request())

    assert result.status.value == "failed"
    assert "extraction failed" in result.gaps[0]
