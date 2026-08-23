"""FastAPI service for the Research & Report Agent."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from research_report_agent import __version__
from research_report_agent.config import (
    PROVIDER_PRESETS,
    ModelConfigInfo,
    Provider,
    get_config_info,
    load_config,
    save_config,
)
from research_report_agent.llm import LLMClient, LLMError
from research_report_agent.orchestrator import Orchestrator
from research_report_agent.report_html import render_report_html
from research_report_agent.runtime_contracts import RunMode, RunRecord, RunStatus
from research_report_agent.storage import Database


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=3, max_length=2000)
    dimensions: list[str] = Field(default_factory=list, max_length=5)
    # Defaults to autonomous so existing clients keep their uninterrupted
    # behaviour; the dashboard opts into guided explicitly.
    mode: RunMode = RunMode.AUTONOMOUS


class GateConfirmRequest(BaseModel):
    """The user's answer to a pending gate.

    Both fields are optional: sending nothing means "proceed as proposed".
    """

    model_config = ConfigDict(extra="forbid")

    goal: str | None = Field(default=None, min_length=3, max_length=2000)
    dimensions: list[str] | None = Field(default=None, max_length=5)
    # Report gate only: "accept" delivers the draft, "rewrite" re-writes it from
    # the findings already gathered -- one model call and no new searches.
    decision: Literal["accept", "rewrite"] = "accept"
    instruction: str | None = Field(default=None, max_length=1000)


class EventListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[dict[str, Any]]


class ModelConfigUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Provider | None = None
    model: str | None = Field(default=None, min_length=1)
    base_url: str | None = None
    api_key: str | None = None


class ProviderPresetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    base_url: str | None
    models: list[str]


def get_database(request: Request) -> Database:
    return request.app.state.database


DatabaseDep = Annotated[Database, Depends(get_database)]


def create_app(
    *,
    database: Database | None = None,
    orchestrator: Orchestrator | None = None,
) -> FastAPI:
    """Create a configured FastAPI application."""

    if database is None:
        database_path = Path(
            os.getenv("RESEARCH_REPORT_AGENT_DB", ".data/research-report-agent.sqlite3")
        )
        database_path.parent.mkdir(parents=True, exist_ok=True)
        database = Database.sqlite(database_path)

    runtime_orchestrator = orchestrator or Orchestrator(database, lambda: LLMClient(load_config()))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await database.create_schema()
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(
        title="Research & Report Agent",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.database = database
    app.state.orchestrator = runtime_orchestrator

    allowed_origins = [
        origin.strip()
        for origin in os.getenv(
            "RESEARCH_REPORT_AGENT_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/model-providers", response_model=list[ProviderPresetResponse])
    async def list_model_providers() -> list[ProviderPresetResponse]:
        return [
            ProviderPresetResponse(id=provider_id, **preset)
            for provider_id, preset in PROVIDER_PRESETS.items()
        ]

    @app.get("/api/model-config", response_model=ModelConfigInfo)
    async def get_model_config() -> ModelConfigInfo:
        return get_config_info()

    @app.post("/api/model-config", response_model=ModelConfigInfo)
    async def update_model_config(request: ModelConfigUpdateRequest) -> ModelConfigInfo:
        if request.base_url and not request.base_url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400,
                detail="base_url must start with http:// or https://",
            )
        save_config(
            provider=request.provider,
            model=request.model,
            base_url=request.base_url,
            api_key=request.api_key,
        )
        return get_config_info()

    @app.post("/api/model-config/test")
    async def test_model_config() -> dict[str, Any]:
        config = load_config()
        if not config.api_key:
            return {"ok": False, "error": "No API key configured"}
        try:
            model_ids = await LLMClient(config).list_model_ids()
        except Exception as exc:  # Connectivity checks must fail closed, not crash.
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "model_found": config.model in model_ids, "model": config.model}

    @app.post(
        "/api/runs",
        response_model=RunRecord,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_run(
        request: RunCreateRequest,
        db: DatabaseDep,
    ) -> RunRecord:
        run_id = f"run_{uuid.uuid4().hex[:16]}"
        run = RunRecord(
            run_id=run_id,
            goal=request.goal,
            dimensions=request.dimensions,
            mode=request.mode,
        )
        await db.runs.create(run)
        try:
            app.state.orchestrator.start(
                run_id,
                request.goal,
                request.dimensions,
                mode=request.mode,
            )
        except LLMError as exc:
            await db.runs.set_terminal(run_id, RunStatus.FAILED, error=str(exc))
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return run

    @app.get("/api/runs", response_model=list[RunRecord])
    async def list_runs(db: DatabaseDep) -> list[RunRecord]:
        return await db.runs.list()

    @app.get("/api/runs/{run_id}", response_model=RunRecord)
    async def get_run(run_id: str) -> RunRecord:
        run = await app.state.database.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @app.delete("/api/runs/{run_id}", response_model=RunRecord)
    async def cancel_run(
        run_id: str,
    ) -> RunRecord:
        run = await app.state.database.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.status is not RunStatus.RUNNING:
            raise HTTPException(status_code=409, detail="Run is not active")
        await app.state.orchestrator.cancel(run.run_id)
        updated = await app.state.database.runs.get(run.run_id)
        if updated is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return updated

    @app.post("/api/runs/{run_id}/confirm", response_model=RunRecord)
    async def confirm_gate(
        run_id: str,
        request: GateConfirmRequest,
        db: DatabaseDep,
    ) -> RunRecord:
        """Answer the run's pending gate and let it continue.

        Resuming re-enters the graph at ``plan`` rather than replaying intake and
        clarification, so confirming costs nothing beyond the research itself.
        """
        run = await db.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.pending_gate is None:
            raise HTTPException(status_code=409, detail="Run is not waiting for input")

        payload = run.pending_gate.payload
        kind = run.pending_gate.kind

        if kind == "confirm_report":
            goal, dimensions = run.goal, list(run.dimensions)
            rewriting = request.decision == "rewrite"
            # Accepting re-enters at the final guardrail; rewriting re-enters at
            # synthesis, which reloads the findings already on record rather
            # than researching anything again.
            resume_from = "synthesize" if rewriting else "final_guardrail"
            instruction = request.instruction if rewriting else None
        else:
            goal = request.goal or str(payload.get("rewritten_goal") or run.goal)
            dimensions = (
                request.dimensions
                if request.dimensions is not None
                else list(payload.get("dimensions") or run.dimensions)
            )
            resume_from, instruction = "plan", None

        await db.runs.close_gate(run_id, goal=goal, dimensions=dimensions)
        try:
            app.state.orchestrator.start(
                run_id,
                goal,
                dimensions,
                mode=run.mode,
                resume_from=resume_from,
                revision_instruction=instruction,
            )
        except LLMError as exc:
            await db.runs.set_terminal(run_id, RunStatus.FAILED, error=str(exc))
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        updated = await db.runs.get(run_id)
        if updated is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return updated

    @app.post(
        "/api/runs/{run_id}/restart",
        response_model=RunRecord,
        status_code=status.HTTP_201_CREATED,
    )
    async def restart_run(run_id: str, db: DatabaseDep) -> RunRecord:
        """Run the same question again as a fresh run.

        The original is left exactly as it was -- its tasks, attempts and events
        stay on record -- because a stopped run is often the thing you want to
        compare the new one against.
        """
        original = await db.runs.get(run_id)
        if original is None:
            raise HTTPException(status_code=404, detail="Run not found")
        if original.status is RunStatus.RUNNING:
            raise HTTPException(
                status_code=409,
                detail="Run is still active -- stop it before starting over",
            )

        new_id = f"run_{uuid.uuid4().hex[:16]}"
        run = RunRecord(
            run_id=new_id,
            goal=original.goal,
            dimensions=list(original.dimensions),
        )
        await db.runs.create(run)
        try:
            app.state.orchestrator.start(new_id, original.goal, list(original.dimensions))
        except LLMError as exc:
            await db.runs.set_terminal(new_id, RunStatus.FAILED, error=str(exc))
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return run

    @app.get("/api/runs/{run_id}/tasks")
    async def list_tasks(
        run_id: str,
    ) -> list[Any]:
        run = await app.state.database.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return await app.state.database.tasks.list(run.run_id)

    @app.get("/api/runs/{run_id}/attempts")
    async def list_attempts(
        run_id: str,
    ) -> list[Any]:
        run = await app.state.database.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return await app.state.database.attempts.list(run.run_id)

    @app.get("/api/runs/{run_id}/events", response_model=EventListResponse)
    async def list_events(
        run_id: str,
        after: int = Query(default=0, ge=0),
    ) -> EventListResponse:
        run = await app.state.database.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        rows = await app.state.database.events.list(run.run_id, after_sequence=after)
        events = []
        for sequence, event in rows:
            payload = event.model_dump(mode="json")
            events.append({"sequence": sequence, **payload})
        return EventListResponse(events=events)

    @app.get("/api/runs/{run_id}/stream")
    async def stream_run(
        run_id: str,
        db: DatabaseDep,
    ) -> Response:
        run = await db.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        terminal_events = {"run.completed", "run.terminated", "run.cancelled"}
        target_run_id = run.run_id

        async def event_stream() -> AsyncIterator[str]:
            last_sequence = 0
            while True:
                rows = await db.events.list(target_run_id, after_sequence=last_sequence)
                for sequence, event in rows:
                    last_sequence = sequence
                    payload = event.model_dump(mode="json")
                    yield (
                        f"id: {sequence}\n"
                        f"event: {event.event_type}\n"
                        f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
                    )
                    if event.event_type in terminal_events:
                        return
                await asyncio.sleep(0.15)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/runs/{run_id}/report")
    async def get_report(
        run_id: str,
    ) -> Any:
        run = await app.state.database.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        report = await app.state.database.reports.get(run.run_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Report not available")
        return report

    @app.get("/api/runs/{run_id}/report.md")
    async def get_report_markdown(
        run_id: str,
    ) -> Response:
        run = await app.state.database.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        report = await app.state.database.reports.get(run.run_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Report not available")
        return Response(
            content=report.markdown,
            media_type="text/markdown",
            headers={"Content-Disposition": 'inline; filename="report.md"'},
        )

    @app.get("/api/runs/{run_id}/report.html")
    async def get_report_html(run_id: str) -> Response:
        run = await app.state.database.runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        report = await app.state.database.reports.get(run.run_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Report not available")
        return Response(
            content=render_report_html(report, goal=run.goal),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="report.html"'},
        )

    return app


__all__ = ["RunCreateRequest", "create_app"]
