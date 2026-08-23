"""LangGraph-backed orchestrator supervisor for research runs."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from research_report_agent.agents.critic import Critic
from research_report_agent.agents.guardrail import FinalGuardrail, IntakeGuardrail
from research_report_agent.agents.planner import Planner
from research_report_agent.agents.synthesizer import Synthesizer
from research_report_agent.contracts import (
    CriticReview,
    ResearchPlan,
    ResearchTask,
    WorkerResult,
    WorkerStatus,
)
from research_report_agent.llm import LLMClient
from research_report_agent.runtime_contracts import (
    AgentEvent,
    AttemptKind,
    ReportDocument,
    RunBudget,
    RunPhase,
    RunStatus,
    RunUsage,
    TaskState,
    ToolName,
    WorkerAttempt,
    WorkerAttemptRequest,
    utc_now,
)
from research_report_agent.storage import Database
from research_report_agent.worker_runtime import WorkerRuntime


class SupervisorState(TypedDict, total=False):
    """State flowing through the LangGraph supervisor graph."""

    run_id: str
    goal: str
    dimensions: list[str]
    route: str
    blocked_reason: str | None
    execution_error: str | None
    plan: ResearchPlan
    results: list[WorkerResult]
    caveats: list[str]
    report: ReportDocument


@dataclass
class _RunAgents:
    """The LLM-backed agent instances used by exactly one run."""

    worker: WorkerRuntime
    planner: Planner
    critic: Critic
    intake_guardrail: IntakeGuardrail
    final_guardrail: FinalGuardrail
    synthesizer: Synthesizer


class Orchestrator:
    """Own run transitions, scheduling, persistence, and bounded worker dispatch."""

    def __init__(
        self,
        database: Database,
        llm_factory: Callable[[], LLMClient],
        *,
        worker_runtime: WorkerRuntime | None = None,
    ) -> None:
        self.database = database
        self._llm_factory = llm_factory
        self._injected_worker = worker_runtime
        self._agents: dict[str, _RunAgents] = {}

        self._background_tasks: dict[str, asyncio.Task[None]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._event_counters: dict[str, int] = {}
        self._finished: set[str] = set()
        self._usage: dict[str, RunUsage] = {}
        self._budgets: dict[str, RunBudget] = {}

        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(SupervisorState)
        graph.add_node("intake_guardrail", self._node_intake)
        graph.add_node("plan", self._node_plan)
        graph.add_node("execute_workers", self._node_execute)
        graph.add_node("review", self._node_review)
        graph.add_node("synthesize", self._node_synthesize)
        graph.add_node("final_guardrail", self._node_final_guardrail)

        graph.add_edge(START, "intake_guardrail")
        graph.add_conditional_edges(
            "intake_guardrail",
            self._route_after_intake,
            {"plan": "plan", "end": END},
        )
        graph.add_edge("plan", "execute_workers")
        graph.add_edge("execute_workers", "review")
        graph.add_conditional_edges(
            "review",
            self._route_after_review,
            {"synthesize": "synthesize", "end": END},
        )
        graph.add_edge("synthesize", "final_guardrail")
        graph.add_edge("final_guardrail", END)
        return graph.compile()

    def start(self, run_id: str, goal: str, dimensions: list[str]) -> None:
        """Start a run in the background without blocking the API request."""

        if run_id in self._background_tasks:
            return
        llm = self._llm_factory()
        self._agents[run_id] = _RunAgents(
            worker=self._injected_worker or WorkerRuntime(llm),
            planner=Planner(llm),
            critic=Critic(llm),
            intake_guardrail=IntakeGuardrail(llm),
            final_guardrail=FinalGuardrail(llm),
            synthesizer=Synthesizer(llm),
        )
        self._cancel_events[run_id] = asyncio.Event()
        # Counters are NOT initialised here -- _run_supervisor hydrates them from
        # the database first, so a run that resumes keeps the spend it already
        # incurred. See _hydrate.
        self._background_tasks[run_id] = asyncio.create_task(
            self._run_supervisor(run_id, goal, dimensions),
            name=f"research-run-{run_id}",
        )

    async def wait(self, run_id: str) -> None:
        """Wait for a background run managed by this orchestrator."""

        task = self._background_tasks.get(run_id)
        if task is not None:
            await asyncio.shield(task)

    async def cancel(self, run_id: str) -> bool:
        """Cancel a running run and preserve completed immutable attempts."""

        cancel_event = self._cancel_events.get(run_id)
        task = self._background_tasks.get(run_id)
        if cancel_event is None or task is None:
            return False

        cancel_event.set()
        if not task.done():
            task.cancel()
            await asyncio.wait({task})
        await self._persist_cancellation(run_id)
        return True

    async def _run_supervisor(
        self,
        run_id: str,
        goal: str,
        dimensions: list[str],
    ) -> None:
        try:
            await self._hydrate(run_id)
            await self.graph.ainvoke({"run_id": run_id, "goal": goal, "dimensions": dimensions})
        except asyncio.CancelledError:
            await self._persist_cancellation(run_id)
        except Exception as exc:
            await self._emit(run_id, "run.failed", data={"error": str(exc)})
            await self._finish(
                run_id,
                RunStatus.FAILED,
                error=f"Orchestrator failed: {exc}",
            )
        finally:
            self._finished.add(run_id)

    async def _node_intake(self, state: SupervisorState) -> dict[str, Any]:
        run_id = state["run_id"]
        await self._set_phase(run_id, RunPhase.INTAKE_GUARDRAIL)
        review = await self._agents[run_id].intake_guardrail.review(run_id, state["goal"])
        await self._emit(
            run_id,
            "intake_guardrail.completed",
            data={"verdict": review.verdict.value},
        )

        if review.verdict.value == "block":
            await self._finish(
                run_id,
                RunStatus.BLOCKED,
                error=review.blocked_reason or "Research goal blocked",
            )
            return {"route": "end", "blocked_reason": review.blocked_reason}
        return {"route": "plan", "blocked_reason": None}

    def _route_after_intake(self, state: SupervisorState) -> str:
        return state.get("route", "end")

    async def _node_plan(self, state: SupervisorState) -> dict[str, Any]:
        run_id = state["run_id"]
        await self._set_phase(run_id, RunPhase.PLANNING)
        plan = await self._agents[run_id].planner.create_plan(
            state["goal"], state.get("dimensions", [])
        )
        await self.database.tasks.replace(run_id, plan.plan_id, 1, plan.tasks)
        await self._emit(
            run_id,
            "plan.validated",
            data={"task_count": len(plan.tasks)},
        )
        return {"plan": plan}

    async def _node_execute(self, state: SupervisorState) -> dict[str, Any]:
        run_id = state["run_id"]
        plan = state["plan"]
        try:
            results = await self._execute_dependency_graph(run_id, plan)
        except Exception as exc:
            return {"execution_error": str(exc), "results": [], "caveats": []}

        caveats = [gap for result in results for gap in result.gaps]
        await self._set_phase(run_id, RunPhase.REVIEWING)
        return {"results": results, "caveats": caveats, "execution_error": None}

    async def _node_review(self, state: SupervisorState) -> dict[str, Any]:
        run_id = state["run_id"]
        if state.get("execution_error"):
            await self._finish(
                run_id,
                RunStatus.FAILED,
                error=state["execution_error"],
            )
            return {"route": "end"}

        review = await self._agents[run_id].critic.review(run_id, state.get("results", []))
        await self._emit(
            run_id,
            "review.completed",
            data={"verdict": review.overall_verdict.value},
        )
        if review.overall_verdict.value == "fail":
            await self._finish(
                run_id,
                RunStatus.FAILED,
                error="No accepted evidence was available for synthesis",
            )
            return {"route": "end"}
        return {"route": "synthesize"}

    def _route_after_review(self, state: SupervisorState) -> str:
        return state.get("route", "end")

    async def _node_synthesize(self, state: SupervisorState) -> dict[str, Any]:
        run_id = state["run_id"]
        await self._set_phase(run_id, RunPhase.SYNTHESIZING)
        report = await self._agents[run_id].synthesizer.synthesize(
            run_id=run_id,
            goal=state["goal"],
            results=state.get("results", []),
            dimensions=state.get("dimensions", []),
        )
        await self.database.reports.save(report)
        await self._emit(
            run_id,
            "synthesis.completed",
            data={"report_id": report.report_id},
        )
        return {"report": report}

    async def _node_final_guardrail(self, state: SupervisorState) -> dict[str, Any]:
        run_id = state["run_id"]
        report = state["report"]
        await self._set_phase(run_id, RunPhase.FINAL_GUARDRAIL)
        review = await self._agents[run_id].final_guardrail.review_markdown(run_id, report.markdown)

        if review.verdict.value == "revise":
            report = report.model_copy(
                update={
                    "markdown": report.markdown
                    + "\n\n> This report is general research and is not purchasing, safety, legal, "
                    "financial, or investment advice.\n"
                }
            )
            review = await self._agents[run_id].final_guardrail.review_markdown(
                run_id, report.markdown
            )

        await self._emit(
            run_id,
            "final_guardrail.completed",
            data={"verdict": review.verdict.value},
        )
        if review.verdict.value == "block":
            await self._finish(
                run_id,
                RunStatus.BLOCKED,
                error=review.blocked_reason or "Final report blocked",
            )
            return {"route": "end", "report": report}

        report = report.model_copy(update={"guardrail_verdict": "allow"})
        await self.database.reports.save(report)
        status = RunStatus.COMPLETE_WITH_CAVEATS if state.get("caveats") else RunStatus.COMPLETE
        await self._finish(run_id, status)
        return {"report": report}

    async def _execute_dependency_graph(
        self,
        run_id: str,
        plan: ResearchPlan,
    ) -> list[WorkerResult]:
        task_states = {task.task_id: TaskState.PENDING for task in plan.tasks}
        results: dict[str, WorkerResult] = {}
        contexts: dict[str, dict[str, Any]] = {}

        while True:
            ready: list[ResearchTask] = []
            for task in plan.tasks:
                if task_states[task.task_id] not in {TaskState.PENDING, TaskState.READY}:
                    continue
                dependency_states = [task_states[item] for item in task.dependencies]
                if all(item is TaskState.COMPLETED for item in dependency_states):
                    ready.append(task)
                elif any(
                    item in {TaskState.FAILED, TaskState.TIMEOUT, TaskState.BLOCKED}
                    for item in dependency_states
                ):
                    task_states[task.task_id] = TaskState.BLOCKED
                    await self.database.tasks.set_state(
                        run_id,
                        task.task_id,
                        TaskState.BLOCKED,
                    )

            if not ready:
                break

            await self._set_phase(run_id, RunPhase.EXECUTING)
            batch = ready[: self._budget(run_id).max_parallel_workers]
            batch_results = await asyncio.gather(
                *[
                    self._execute_attempt(
                        run_id=run_id,
                        plan=plan,
                        task=task,
                        attempt_kind=AttemptKind.INITIAL,
                        upstream_context={
                            key: value
                            for dependency in task.dependencies
                            for key, value in contexts.get(dependency, {}).items()
                        },
                    )
                    for task in batch
                ]
            )
            for task, result in zip(batch, batch_results, strict=True):
                results[task.task_id] = result
                task_states[task.task_id] = self._task_state(result)
                contexts[task.task_id] = result.produced_context

        ordered = [results[task.task_id] for task in plan.tasks if task.task_id in results]
        review = await self._agents[run_id].critic.review(run_id, ordered)
        if review.overall_verdict.value == "fail":
            return ordered
        return await self._run_critic_revisions(
            run_id=run_id,
            plan=plan,
            results=ordered,
            review=review,
            contexts=contexts,
        )

    async def _run_critic_revisions(
        self,
        *,
        run_id: str,
        plan: ResearchPlan,
        results: list[WorkerResult],
        review: CriticReview,
        contexts: dict[str, dict[str, Any]],
    ) -> list[WorkerResult]:
        tasks_by_id = {task.task_id: task for task in plan.tasks}
        attempts = await self.database.tasks.list(run_id)
        attempt_counts = {item.task.task_id: item.attempt_count for item in attempts}
        revised = list(results)

        for task_review in review.task_reviews:
            if task_review.verdict.value != "revise":
                continue
            if attempt_counts.get(task_review.task_id, 0) >= 2:
                continue
            task = tasks_by_id[task_review.task_id]
            result = await self._execute_attempt(
                run_id=run_id,
                plan=plan,
                task=task,
                attempt_kind=AttemptKind.CRITIC_REVISION,
                upstream_context=contexts.get(task.task_id, {}),
            )
            revised = [result if item.task_id == task.task_id else item for item in revised]
        return revised

    async def _execute_attempt(
        self,
        *,
        run_id: str,
        plan: ResearchPlan,
        task: ResearchTask,
        attempt_kind: AttemptKind,
        upstream_context: dict[str, Any],
    ) -> WorkerResult:
        attempt_number = await self.database.tasks.increment_attempt(
            run_id,
            task.task_id,
        )
        attempt_id = f"{run_id}_{task.task_id}_attempt_{attempt_number:03d}"
        await self.database.tasks.set_state(run_id, task.task_id, TaskState.RUNNING)
        await self._emit(
            run_id,
            "worker.attempt.started",
            task_id=task.task_id,
            attempt_id=attempt_id,
            data={"question": task.question, "attempt_kind": attempt_kind.value},
        )

        request = WorkerAttemptRequest(
            run_id=run_id,
            plan_id=plan.plan_id,
            plan_version=1,
            task_id=task.task_id,
            attempt_id=attempt_id,
            attempt_kind=attempt_kind,
            question=task.question,
            success_criteria=task.success_criteria,
            allowed_tools=[ToolName(tool) for tool in task.required_tools],
            upstream_context=upstream_context,
            limits=self._budget(run_id),
        )

        started_at = utc_now()
        tool_calls_before = self._agents[run_id].worker.tools.call_count
        try:
            result = await asyncio.wait_for(
                self._agents[run_id].worker.execute_attempt(
                    request,
                    cancel_event=self._cancel_events[run_id],
                ),
                timeout=self._budget(run_id).attempt_timeout_seconds,
            )
            error = None
        except TimeoutError:
            result = self._attempt_failure(
                task.task_id,
                f"Worker exceeded {self._budget(run_id).attempt_timeout_seconds} seconds",
            )
            error = result.gaps[0]
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            result = self._attempt_failure(task.task_id, f"Worker failed: {exc}")
            error = result.gaps[0]

        task_state = self._task_state(result)
        await self.database.attempts.add(
            WorkerAttempt(
                run_id=run_id,
                plan_id=plan.plan_id,
                plan_version=1,
                task_id=task.task_id,
                attempt_id=attempt_id,
                attempt_kind=attempt_kind,
                state=task_state,
                started_at=started_at,
                completed_at=utc_now(),
                result=result,
                error=error,
            )
        )
        await self.database.tasks.set_state(run_id, task.task_id, task_state)
        if result.produced_context:
            await self.database.tasks.set_produced_context(
                run_id,
                task.task_id,
                result.produced_context,
            )

        self._increment_usage(
            run_id,
            llm_calls=1,
            tool_calls=self._agents[run_id].worker.tools.call_count - tool_calls_before,
        )
        await self._emit(
            run_id,
            "worker.attempt.completed",
            task_id=task.task_id,
            attempt_id=attempt_id,
            data={
                "status": result.status.value,
                "findings_count": len(result.findings),
                "sources_count": len(result.sources),
            },
        )
        return result

    def _task_state(self, result: WorkerResult) -> TaskState:
        return {
            WorkerStatus.COMPLETED: TaskState.COMPLETED,
            WorkerStatus.PARTIAL: TaskState.PARTIAL,
            WorkerStatus.FAILED: TaskState.FAILED,
            WorkerStatus.TIMEOUT: TaskState.TIMEOUT,
            WorkerStatus.INVALID_OUTPUT: TaskState.FAILED,
            WorkerStatus.BLOCKED: TaskState.BLOCKED,
        }[result.status]

    def _attempt_failure(self, task_id: str, message: str) -> WorkerResult:
        return WorkerResult(
            task_id=task_id,
            status=WorkerStatus.FAILED,
            summary=message,
            gaps=[message],
        )

    async def _set_phase(self, run_id: str, phase: RunPhase) -> None:
        await self.database.runs.set_phase(run_id, phase)
        # A phase boundary is the natural checkpoint: cheap, already durable,
        # and the only place a run can be interrupted between units of work.
        await self._flush_usage(run_id)
        await self._emit(
            run_id,
            "run.phase.changed",
            data={"phase": phase.value},
        )

    async def _emit(
        self,
        run_id: str,
        event_type: str,
        *,
        task_id: str | None = None,
        attempt_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self._event_counters[run_id] = self._event_counters.get(run_id, 0) + 1
        await self.database.events.append(
            AgentEvent(
                event_id=f"{run_id}_event_{self._event_counters[run_id]:06d}",
                run_id=run_id,
                event_type=event_type,
                task_id=task_id,
                attempt_id=attempt_id,
                data=data or {},
            )
        )

    async def _finish(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
    ) -> None:
        if run_id in self._finished:
            return
        self._finished.add(run_id)
        self._agents.pop(run_id, None)
        usage = self._usage.get(run_id, RunUsage())
        await self.database.runs.set_usage(run_id, usage)
        await self.database.runs.set_terminal(run_id, status, error=error)
        await self._emit(
            run_id,
            "run.completed" if status.value.startswith("complete") else "run.terminated",
            data={"status": status.value, "error": error},
        )

    async def _persist_cancellation(self, run_id: str) -> None:
        tasks = await self.database.tasks.list(run_id)
        for task in tasks:
            if task.state in {TaskState.RUNNING, TaskState.READY, TaskState.PENDING}:
                await self.database.tasks.set_state(
                    run_id,
                    task.task.task_id,
                    TaskState.CANCELLED,
                )
        await self._emit(run_id, "run.cancelled")
        await self._finish(run_id, RunStatus.CANCELLED)

    async def _hydrate(self, run_id: str) -> None:
        """Restore this run's counters from the database instead of zeroing them.

        Usage, budget and the event counter used to be re-initialised on every
        ``start()``. That was invisible while a run always executed inside one
        continuous background task, but it means a run that pauses and later
        resumes -- in a new process, or after a restart -- comes back believing
        it has spent nothing. Budget caps would then be enforced against zero,
        so pausing would silently refill the quota, and the event counter would
        re-issue ids that already exist.

        The database is the source of truth for all three.
        """
        record = await self.database.runs.get(run_id)
        if record is None:
            self._usage.setdefault(run_id, RunUsage())
            self._budgets.setdefault(run_id, RunBudget())
            self._event_counters.setdefault(run_id, 0)
            return

        self._usage[run_id] = record.usage
        self._budgets[run_id] = record.budget
        self._event_counters[run_id] = await self.database.events.count(run_id)

    async def _flush_usage(self, run_id: str) -> None:
        """Write usage through to the database at a phase boundary.

        Usage used to reach the database only in ``_finish``, so an in-flight
        run reported zeros and a run that never terminates -- one paused at a
        gate, for instance -- never persisted its spend at all.
        """
        usage = self._usage.get(run_id)
        if usage is not None:
            await self.database.runs.set_usage(run_id, usage)

    def _budget(self, run_id: str) -> RunBudget:
        return self._budgets.setdefault(run_id, RunBudget())

    def _increment_usage(
        self,
        run_id: str,
        *,
        llm_calls: int = 0,
        tool_calls: int = 0,
    ) -> None:
        current = self._usage.setdefault(run_id, RunUsage())
        self._budgets.setdefault(run_id, RunBudget())
        self._usage[run_id] = current.model_copy(
            update={
                "llm_calls": current.llm_calls + llm_calls,
                "tool_calls": current.tool_calls + tool_calls,
            }
        )


__all__ = ["Orchestrator", "SupervisorState"]
