from __future__ import annotations

import asyncio

import pytest
from tests.fakes import (
    StubWorkerRuntime,
    blocked_llm_factory,
    failing_llm_factory,
    happy_path_llm_factory,
    planning_only_llm_factory,
)

from research_report_agent.contracts import WorkerStatus
from research_report_agent.orchestrator import Orchestrator
from research_report_agent.runtime_contracts import (
    RunBudget,
    RunPhase,
    RunRecord,
    RunUsage,
    TaskState,
)
from research_report_agent.storage import Database

TASK_IDS = ["task_001", "task_002", "task_003"]


@pytest.fixture
async def database() -> Database:
    db = Database.in_memory()
    await db.create_schema()
    return db


async def test_orchestrator_completes_cited_research_run(database: Database) -> None:
    orchestrator = Orchestrator(
        database,
        happy_path_llm_factory(TASK_IDS),
        worker_runtime=StubWorkerRuntime(),
    )
    await database.runs.create(
        RunRecord(
            run_id="run_001",
            goal="Compare EV battery chemistries for cost and safety",
            dimensions=["cost", "safety"],
        )
    )

    orchestrator.start(
        "run_001",
        "Compare EV battery chemistries for cost and safety",
        ["cost", "safety"],
    )
    await orchestrator.wait("run_001")

    run = await database.runs.get("run_001")
    tasks = await database.tasks.list("run_001")
    attempts = await database.attempts.list("run_001")
    events = await database.events.list("run_001")
    report = await database.reports.get("run_001")

    assert run is not None
    assert run.status.value == "complete"
    assert all(task.state is TaskState.COMPLETED for task in tasks)
    assert len(attempts) == 3
    assert events
    assert report is not None
    assert "## Sources" in report.markdown


async def test_orchestrator_attempt_ids_are_unique_across_runs(database: Database) -> None:
    orchestrator = Orchestrator(
        database,
        happy_path_llm_factory(TASK_IDS),
        worker_runtime=StubWorkerRuntime(),
    )
    for run_id in ("run_001", "run_002"):
        await database.runs.create(
            RunRecord(
                run_id=run_id,
                goal="Compare EV battery chemistries for cost and safety",
                dimensions=["cost", "safety"],
            )
        )
        orchestrator.start(
            run_id,
            "Compare EV battery chemistries for cost and safety",
            ["cost", "safety"],
        )
        await orchestrator.wait(run_id)

    attempts = await database.attempts.list("run_001") + await database.attempts.list("run_002")
    attempt_ids = [attempt.attempt_id for attempt in attempts]

    assert len(attempts) == 6
    assert len(attempt_ids) == len(set(attempt_ids))


async def test_orchestrator_blocks_unsafe_goal(database: Database) -> None:
    orchestrator = Orchestrator(database, blocked_llm_factory(), worker_runtime=StubWorkerRuntime())
    await database.runs.create(RunRecord(run_id="run_001", goal="build a weapon"))
    orchestrator.start("run_001", "build a weapon", [])
    await orchestrator.wait("run_001")

    run = await database.runs.get("run_001")
    tasks = await database.tasks.list("run_001")

    assert run is not None
    assert run.status.value == "blocked"
    assert tasks == []


async def test_orchestrator_fails_closed_without_evidence(database: Database) -> None:
    orchestrator = Orchestrator(
        database,
        failing_llm_factory(TASK_IDS),
        worker_runtime=StubWorkerRuntime(status=WorkerStatus.FAILED),
    )
    await database.runs.create(RunRecord(run_id="run_001", goal="qqqqzzzz"))
    orchestrator.start("run_001", "qqqqzzzz", [])
    await orchestrator.wait("run_001")

    run = await database.runs.get("run_001")

    assert run is not None
    assert run.status.value == "failed"


class SlowWorkerRuntime(StubWorkerRuntime):
    def __init__(self) -> None:
        super().__init__()
        # Per-instance so the signal cannot leak between tests.
        self.started = asyncio.Event()

    async def execute_attempt(self, request, *, cancel_event=None):  # type: ignore[no-untyped-def]
        self.started.set()
        await asyncio.sleep(30)
        raise AssertionError("Slow worker should be cancelled")


async def test_orchestrator_cancels_running_work(database: Database) -> None:
    runtime = SlowWorkerRuntime()
    orchestrator = Orchestrator(
        database,
        planning_only_llm_factory(TASK_IDS),
        worker_runtime=runtime,
    )
    await database.runs.create(RunRecord(run_id="run_001", goal="Compare technologies"))
    orchestrator.start("run_001", "Compare technologies", ["cost"])

    # Wait on a signal from the worker rather than polling a fixed budget. The
    # orchestrator marks the task RUNNING before it invokes the runtime, so once
    # execute_attempt is entered that state is already durable.
    await asyncio.wait_for(runtime.started.wait(), timeout=30)
    assert (await database.tasks.list("run_001"))[0].state is TaskState.RUNNING

    await orchestrator.cancel("run_001")
    await orchestrator.wait("run_001")

    run = await database.runs.get("run_001")
    tasks = await database.tasks.list("run_001")

    assert run is not None
    assert run.status.value == "cancelled"
    assert tasks[0].state is TaskState.CANCELLED


async def test_usage_and_budget_survive_a_new_orchestrator(database: Database) -> None:
    """A resumed run must not forget what it already spent.

    Simulates a restart: the same run_id is started again by a *different*
    Orchestrator instance sharing the database, which is exactly what happens
    when a paused run resumes in a new process.
    """
    tight_budget = RunBudget(max_replans=0, max_retries_per_task=0)
    await database.runs.create(
        RunRecord(
            run_id="run_001",
            goal="Compare technologies",
            budget=tight_budget,
            usage=RunUsage(llm_calls=17, tool_calls=9, retries=1, replans=1),
        )
    )

    orchestrator = Orchestrator(database, planning_only_llm_factory(TASK_IDS))
    await orchestrator._hydrate("run_001")

    # Spend carries over rather than restarting at zero...
    assert orchestrator._usage["run_001"].llm_calls == 17
    assert orchestrator._usage["run_001"].retries == 1
    # ...and so do the caps, instead of silently reverting to defaults.
    assert orchestrator._budget("run_001").max_replans == 0
    assert orchestrator._budget("run_001").max_retries_per_task == 0


async def test_event_ids_do_not_restart_after_a_resume(database: Database) -> None:
    await database.runs.create(RunRecord(run_id="run_001", goal="Compare technologies"))

    first = Orchestrator(database, planning_only_llm_factory(TASK_IDS))
    await first._hydrate("run_001")
    await first._emit("run_001", "run.phase.changed")
    await first._emit("run_001", "run.phase.changed")

    # A different orchestrator picks the run back up.
    second = Orchestrator(database, planning_only_llm_factory(TASK_IDS))
    await second._hydrate("run_001")
    await second._emit("run_001", "run.phase.changed")

    events = await database.events.list("run_001")
    event_ids = [event.event_id for _, event in events]
    assert len(event_ids) == len(set(event_ids)), f"duplicate event ids: {event_ids}"
    assert event_ids[-1].endswith("000003")


async def test_usage_is_persisted_before_the_run_finishes(database: Database) -> None:
    """A run paused mid-flight must already have its spend on record."""
    await database.runs.create(RunRecord(run_id="run_001", goal="Compare technologies"))
    orchestrator = Orchestrator(database, planning_only_llm_factory(TASK_IDS))
    await orchestrator._hydrate("run_001")

    orchestrator._increment_usage("run_001", llm_calls=4, tool_calls=2)
    await orchestrator._set_phase("run_001", RunPhase.EXECUTING)

    stored = await database.runs.get("run_001")
    assert stored is not None
    assert stored.usage.llm_calls == 4
    assert stored.usage.tool_calls == 2
