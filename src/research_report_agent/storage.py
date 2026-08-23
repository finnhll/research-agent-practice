from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from research_report_agent.contracts import ResearchTask
from research_report_agent.runtime_contracts import (
    AgentEvent,
    PendingGate,
    PlannedTaskRecord,
    ReportDocument,
    RunBudget,
    RunMode,
    RunPhase,
    RunRecord,
    RunStatus,
    RunUsage,
    TaskState,
    WorkerAttempt,
    utc_now,
)


def dump_model(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


class ORMBase(DeclarativeBase):
    pass


class RunRow(ORMBase):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    goal: Mapped[str] = mapped_column(Text)
    dimensions: Mapped[list[str]] = mapped_column(JSON)
    phase: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(48))
    budget: Mapped[dict[str, Any]] = mapped_column(JSON)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(32), default=RunMode.AUTONOMOUS.value)
    pending_gate: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TaskRow(ORMBase):
    __tablename__ = "tasks"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64))
    plan_version: Mapped[int] = mapped_column(Integer)
    task: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(32))
    attempt_count: Mapped[int] = mapped_column(Integer)
    produced_context: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AttemptRow(ORMBase):
    __tablename__ = "attempts"

    attempt_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), index=True)
    task_id: Mapped[str] = mapped_column(String(64))
    attempt: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EventRow(ORMBase):
    __tablename__ = "events"

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(96))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), index=True)
    event: Mapped[dict[str, Any]] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ReportRow(ORMBase):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("report_id"),)

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(96))
    report: Mapped[dict[str, Any]] = mapped_column(JSON)
    markdown: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RunRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(self, run: RunRecord) -> None:
        async with self._sessionmaker() as session:
            session.add(
                RunRow(
                    run_id=run.run_id,
                    goal=run.goal,
                    dimensions=run.dimensions,
                    phase=run.phase.value,
                    status=run.status.value,
                    budget=dump_model(run.budget),
                    usage=dump_model(run.usage),
                    mode=run.mode.value,
                    pending_gate=dump_model(run.pending_gate) if run.pending_gate else None,
                    created_at=run.created_at,
                    updated_at=run.updated_at,
                    completed_at=run.completed_at,
                    error=run.error,
                )
            )
            await session.commit()

    async def get(self, run_id: str) -> RunRecord | None:
        async with self._sessionmaker() as session:
            row = await session.get(RunRow, run_id)
            return RunRecord.model_validate(row) if row else None

    async def list(self) -> list[RunRecord]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(select(RunRow).order_by(RunRow.created_at.desc()))
            return [RunRecord.model_validate(row) for row in rows]

    async def set_phase(self, run_id: str, phase: RunPhase) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                raise LookupError(f"unknown run: {run_id}")
            row.phase = RunPhase(phase).value
            row.updated_at = utc_now()
            await session.commit()

    async def set_usage(self, run_id: str, usage: RunUsage) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                raise LookupError(f"unknown run: {run_id}")
            row.usage = dump_model(usage)
            row.updated_at = utc_now()
            await session.commit()

    async def set_budget(self, run_id: str, budget: RunBudget) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                raise LookupError(f"unknown run: {run_id}")
            row.budget = dump_model(budget)
            row.updated_at = utc_now()
            await session.commit()

    async def open_gate(self, run_id: str, gate: PendingGate, phase: RunPhase) -> None:
        """Park the run on a gate: paused, not running, not terminal."""
        async with self._sessionmaker() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                raise LookupError(f"unknown run: {run_id}")
            row.pending_gate = dump_model(gate)
            row.phase = RunPhase(phase).value
            row.status = RunStatus.AWAITING_INPUT.value
            row.updated_at = utc_now()
            await session.commit()

    async def close_gate(self, run_id: str, *, goal: str, dimensions: list[str]) -> None:
        """Clear the gate and put the run back in flight, with the confirmed question."""
        async with self._sessionmaker() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                raise LookupError(f"unknown run: {run_id}")
            row.pending_gate = None
            row.goal = goal
            row.dimensions = dimensions
            row.status = RunStatus.RUNNING.value
            row.updated_at = utc_now()
            await session.commit()

    async def set_terminal(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
    ) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                raise LookupError(f"unknown run: {run_id}")
            now = utc_now()
            row.phase = RunPhase.TERMINAL.value
            row.status = status.value
            row.error = error
            row.updated_at = now
            row.completed_at = now
            await session.commit()


class TaskRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def replace(
        self,
        run_id: str,
        plan_id: str,
        plan_version: int,
        tasks: Sequence[ResearchTask],
    ) -> None:
        async with self._sessionmaker() as session:
            existing = await session.scalars(select(TaskRow).where(TaskRow.run_id == run_id))
            for row in existing:
                await session.delete(row)

            for task in tasks:
                record = PlannedTaskRecord(
                    run_id=run_id,
                    plan_id=plan_id,
                    plan_version=plan_version,
                    task=task,
                )
                payload = dump_model(record)
                session.add(
                    TaskRow(
                        run_id=run_id,
                        task_id=task.task_id,
                        plan_id=plan_id,
                        plan_version=plan_version,
                        task=payload["task"],
                        state=payload["state"],
                        attempt_count=payload["attempt_count"],
                        produced_context=payload["produced_context"],
                        created_at=record.created_at,
                        updated_at=record.updated_at,
                    )
                )
            await session.commit()

    async def list(self, run_id: str) -> list[PlannedTaskRecord]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(
                select(TaskRow)
                .where(TaskRow.run_id == run_id)
                .order_by(TaskRow.created_at, TaskRow.task_id)
            )
            return [PlannedTaskRecord.model_validate(row) for row in rows]

    async def set_state(self, run_id: str, task_id: str, state: TaskState) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(TaskRow, (run_id, task_id))
            if row is None:
                raise LookupError(f"unknown task: {task_id}")
            row.state = state.value
            row.updated_at = utc_now()
            await session.commit()

    async def increment_attempt(self, run_id: str, task_id: str) -> int:
        async with self._sessionmaker() as session:
            row = await session.get(TaskRow, (run_id, task_id))
            if row is None:
                raise LookupError(f"unknown task: {task_id}")
            row.attempt_count += 1
            row.updated_at = utc_now()
            await session.commit()
            return row.attempt_count

    async def set_produced_context(
        self,
        run_id: str,
        task_id: str,
        context: dict[str, Any],
    ) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(TaskRow, (run_id, task_id))
            if row is None:
                raise LookupError(f"unknown task: {task_id}")
            row.produced_context = context
            row.updated_at = utc_now()
            await session.commit()


class AttemptRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def add(self, attempt: WorkerAttempt) -> None:
        async with self._sessionmaker() as session:
            session.add(
                AttemptRow(
                    attempt_id=attempt.attempt_id,
                    run_id=attempt.run_id,
                    task_id=attempt.task_id,
                    attempt=dump_model(attempt),
                    created_at=attempt.started_at,
                )
            )
            await session.commit()

    async def list(self, run_id: str) -> list[WorkerAttempt]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(
                select(AttemptRow)
                .where(AttemptRow.run_id == run_id)
                .order_by(AttemptRow.created_at, AttemptRow.attempt_id)
            )
            return [WorkerAttempt.model_validate(row.attempt) for row in rows]


class EventRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def append(self, event: AgentEvent) -> int:
        async with self._sessionmaker() as session:
            row = EventRow(
                event_id=event.event_id,
                run_id=event.run_id,
                event=dump_model(event),
                timestamp=event.timestamp,
            )
            session.add(row)
            await session.flush()
            sequence = int(row.sequence)
            await session.commit()
            return sequence

    async def list(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[tuple[int, AgentEvent]]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(
                select(EventRow)
                .where(EventRow.run_id == run_id, EventRow.sequence > after_sequence)
                .order_by(EventRow.sequence)
            )
            return [(row.sequence, AgentEvent.model_validate(row.event)) for row in rows]

    async def count(self, run_id: str) -> int:
        """How many events this run has already emitted.

        Used to restore the orchestrator's event counter, so a resumed run
        keeps numbering where it left off instead of re-issuing event_000001.
        """
        async with self._sessionmaker() as session:
            total = await session.scalar(
                select(func.count()).select_from(EventRow).where(EventRow.run_id == run_id)
            )
            return int(total or 0)


class ReportRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def save(self, report: ReportDocument) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(ReportRow, report.run_id)
            if row is None:
                session.add(
                    ReportRow(
                        run_id=report.run_id,
                        report_id=report.report_id,
                        report=dump_model(report),
                        markdown=report.markdown,
                        created_at=report.created_at,
                    )
                )
            else:
                row.report_id = report.report_id
                row.report = dump_model(report)
                row.markdown = report.markdown
                row.created_at = report.created_at
            await session.commit()

    async def get(self, run_id: str) -> ReportDocument | None:
        async with self._sessionmaker() as session:
            row = await session.get(ReportRow, run_id)
            return ReportDocument.model_validate(row.report) if row else None


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        self.runs = RunRepository(sessionmaker)
        self.tasks = TaskRepository(sessionmaker)
        self.attempts = AttemptRepository(sessionmaker)
        self.events = EventRepository(sessionmaker)
        self.reports = ReportRepository(sessionmaker)

    @classmethod
    def in_memory(cls) -> Database:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        return cls(engine)

    @classmethod
    def sqlite(cls, path: str | Path) -> Database:
        return cls(create_async_engine(f"sqlite+aiosqlite:///{path}"))

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(ORMBase.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()


__all__ = ["Database"]
