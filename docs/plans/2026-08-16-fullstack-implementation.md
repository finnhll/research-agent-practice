# Fullstack Research & Report Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement the approved Python/LangGraph orchestrator-workers backend, FastAPI service, React frontend, tests, and browser-ready end-to-end workflow.

**Architecture:** FastAPI owns external requests and persistence. An async orchestrator owns run state, scheduling, retries, budgets, events, cancellation, and terminal outcomes. Workers execute one bounded ReAct attempt and return typed results. React consumes REST plus SSE and never contacts model providers or tools directly.

**Tech Stack:** Python 3.11, LangGraph, FastAPI, Pydantic, SQLAlchemy async SQLite, pytest, React, TypeScript, Vite, TanStack Query, React Router, Vitest, Testing Library.

**Spec:** `docs/spec/design.md`

## Global Constraints

- Default backend port: `8000`.
- Default frontend dev port: `5173`.
- Runtime mode defaults to deterministic local agents and tools.
- External model/search credentials must come from environment variables.
- Frontend must not call model or tool providers directly.
- Orchestrator is the sole owner of shared state and transitions.
- Every worker attempt is immutable and identity-bound.
- Worker loops enforce reasoning-step, tool-call, and timeout limits.
- Every run reaches `complete`, `complete_with_caveats`, `failed`, `blocked`, or `cancelled`.
- All backend schemas reject undeclared fields.
- All API list endpoints are ordered deterministically.
- CI must run backend lint/tests and frontend typecheck/tests/build.

---

### Task 1: Runtime contracts

**Files:**
- Modify: `src/research_report_agent/contracts.py`
- Create: `src/research_report_agent/runtime_contracts.py`
- Test: `tests/test_runtime_contracts.py`

**Interfaces:**
- Produces `RunPhase`, `RunStatus`, `TaskState`, `WorkerAttempt`, `WorkerAttemptRequest`, `RunBudget`, `RunUsage`, `AgentEvent`, `ToolRequest`, `ToolResult`, `ReportDocument`

- [x] Write failing tests for:
  - Phase/status/task-state enum values
  - Budget limits
  - Immutable worker attempt IDs
  - Tool result timestamps
  - Event payload shape
- [x] Implement strict Pydantic runtime models.
- [x] Run `pytest tests/test_runtime_contracts.py -q`.
- [x] Commit: `feat: add runtime contracts`

### Task 2: Persistence

**Files:**
- Create: `src/research_report_agent/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces `Database`
- Produces `RunRepository.create_run`
- Produces `RunRepository.list_runs`
- Produces `RunRepository.get_run`
- Produces `RunRepository.set_terminal_state`
- Produces `TaskRepository.replace_tasks`
- Produces `AttemptRepository.add_result`
- Produces `EventRepository.append`
- Produces `ReportRepository.save`

- [x] Write failing tests using an in-memory SQLite database.
- [x] Implement async SQLAlchemy models and repositories.
- [x] Enforce unique run/task/attempt IDs.
- [x] Store JSON payloads as normalized JSON strings.
- [x] Run `pytest tests/test_storage.py -q`.
- [x] Commit: `feat: add persistent run storage`

### Task 3: Deterministic agent tools

**Files:**
- Create: `src/research_report_agent/tools.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Produces `ToolExecutor.execute(request: ToolRequest) -> ToolResult`
- Supports tool names `web_search`, `fetch_page`, `calculator`

- [x] Write tests for successful search, fetch, calculator, invalid input, unknown tool, timeout, and call limits.
- [x] Implement deterministic local search corpus.
- [x] Implement URL parsing and SSRF blocking for loopback/private/link-local/reserved addresses.
- [x] Implement deterministic arithmetic parser without `eval`.
- [+- ] Run `pytest tests/test_tools.py -q`.
- [x] Commit: `feat: add bounded worker tools`

### Task 4: Worker ReAct runtime

**Files:**
- Create: `src/research_report_agent/worker_runtime.py`
- Test: `tests/test_worker_runtime.py`

**Interfaces:**
- Produces `WorkerRuntime.execute_attempt(request: WorkerAttemptRequest) -> WorkerResult`

- [x] Write tests for completion, partial result, tool exhaustion, invalid output, and cancellation.
- [x] Implement bounded loop:
  - Assess evidence
  - Select next tool
  - Execute typed request
  - Sanitize observation
  - Enforce limits
  - Return structured result
- [x] Run `pytest tests/test_worker_runtime.py -q`.
- [x] Commit: `feat: add worker react runtime`

### Task 5: Agents

**Files:**
- Create: `src/research_report_agent/agents/__init__.py`
- Create: `src/research_report_agent/agents/guardrail.py`
- Create: `src/research_report_agent/agents/planner.py`
- Create: `src/research_report_agent/agents/critic.py`
- Create: `src/research_report_agent/agents/synthesizer.py`
- Test: `tests/test_agents.py`

**Interfaces:**
- Produces `IntakeGuardrail.review(goal: str) -> GuardrailReview`
- Produces `Planner.create_plan(goal: str, dimensions: list[str]) -> ResearchPlan`
- Produces `Critic.review(results: list[WorkerResult]) -> CriticReview`
- Produces `Synthesizer.synthesize(...) -> ReportDocument`

- [x] Write deterministic tests for safe/unsafe intake, valid plan, weak result revision, and cited synthesis.
- [x] Implement deterministic local MVP agents with typed outputs.
- [x] Ensure synthesizer uses accepted findings only.
- [x] Commit: `feat: add typed agent nodes`

### Task 6: Orchestrator supervisor

**Files:**
- Create: `src/research_report_agent/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Produces `Orchestrator.start(run_id, goal, dimensions)`
- Produces `Orchestrator.cancel(run_id)`

- [x] Write tests for successful run, unsafe input, partial failure, cancellation, and terminal state.
- [x] Implement async supervisor loop with:
  - Intake guardrail
  - Planning
  - Dependency scheduling
  - Bounded parallel dispatch
  - Immutable attempt persistence
  - Critic
  - Synthesizer
  - Final guardrail
  - Event emission
  - Terminal transitions
- [x] Commit: `feat: add orchestrator supervisor`

### Task 7: FastAPI application

**Files:**
- Create: `src/research_report_agent/api.py`
- Create: `src/research_report_agent/main.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces `create_app(database: Database | None = None) -> FastAPI`
- Exposes `/health`
- Exposes `/api/runs`
- Exposes `/api/runs/{run_id}`
- Exposes `/api/runs/{run_id}/tasks`
- Exposes `/api/runs/{run_id}/attempts`
- Exposes `/api/runs/{run_id}/events`
- Exposes `/api/runs/{run_id}/stream`
- Exposes `/api/runs/{run_id}/report`
- Exposes `/api/runs/{run_id}/report.md`

- [x] Write API tests with `httpx.AsyncClient`.
- [x] Implement Pydantic request/response schemas.
- [x] Implement SSE event stream from persisted events plus live subscriber queue.
- [x] Implement cancellation.
- [x] Commit: `feat: add fastapi service`

### Task 8: Frontend foundation

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/types.ts`
- Create: `frontend/src/styles.css`

**Interfaces:**
- Produces `api.createRun`
- Produces `api.listRuns`
- Produces `api.getRun`
- Produces `api.listTasks`
- Produces `api.listAttempts`
- Produces `api.listEvents`
- Produces `api.getReport`
- Produces `api.cancelRun`

- [x] Add React/Vite/TypeScript dependencies and scripts.
- [x] Implement typed API client.
- [x] Implement routes `/` and `/runs/:runId`.
- [x] Commit: `feat: add react frontend foundation`

### Task 9: Frontend run dashboard

**Files:**
- Create: `frontend/src/components/NewRunForm.tsx`
- Create: `frontend/src/components/RunList.tsx`
- Create: `frontend/src/components/RunDashboard.tsx`
- Create: `frontend/src/components/TaskCard.tsx`
- Create: `frontend/src/components/AttemptCard.tsx`
- Create: `frontend/src/components/EventTimeline.tsx`
- Create: `frontend/src/hooks/useRunStream.ts`

**Interfaces:**
- Produces live run refresh through SSE.
- Produces cancellation action.
- Produces task/attempt/event rendering.

- [x] Implement form validation and submission.
- [x] Implement status/phase badges.
- [x] Implement live event stream and query invalidation.
- [x] Implement report and trace sections.
- [x] Commit: `feat: add live run dashboard`

### Task 10: Report viewer

**Files:**
- Create: `frontend/src/components/ReportViewer.tsx`
- Create: `frontend/src/components/SourceList.tsx`

**Interfaces:**
- Renders structured report.
- Downloads Markdown from backend.

- [x] Render executive summary, sections, comparison table, conclusions, confidence, limitations, and sources.
- [x] Add Markdown download/copy actions.
- [x] Commit: `feat: add report viewer`

### Task 11: Frontend tests

**Files:**
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/test/App.test.tsx`
- Create: `frontend/src/test/RunDashboard.test.tsx`
- Create: `frontend/vitest.config.ts`

- [x] Test run creation form.
- [x] Test dashboard rendering.
- [x] Test SSE refresh.
- [x] Test report viewer.
- [x] Commit: `test: add frontend coverage`

### Task 12: CI and documentation

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `pyproject.toml`

- [x] Add backend dependencies: `fastapi`, `uvicorn`, `sqlalchemy`, `aiosqlite`, `httpx`.
- [x] Add frontend scripts: `typecheck`, `test`, `build`.
- [x] Add CI frontend job.
- [x] Document local setup and API surface.
- [x] Commit: `ci: validate fullstack application`

### Task 13: End-to-end verification

**Files:**
- Create: `scripts/dev.sh`

- [x] Start backend and frontend.
- [x] Create a run through the UI.
- [x] Verify SSE progress.
- [x] Verify final report.
- [x] Verify cancellation endpoint.
- [x] Run all checks:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/pytest -q
cd frontend && npm run typecheck && npm run test -- --run && npm run build
```

- [x] Commit: `test: verify fullstack workflow`

### Task 14: Pull request

- [x] Push `feat/fullstack-agent-platform`.
- [x] Open PR into `main`.
- [x] Confirm CI passes.
- [x] Provide browser and API verification summary.

Browser run `run_6535c7b8a76a4343` reached `complete`, displayed three completed tasks, three worker attempts, the SSE event trace, the guardrail-approved report, and its source appendix. `/health` returned `{"status":"ok"}`, the Markdown endpoint returned the rendered report, and the browser console contained no errors or warnings.
