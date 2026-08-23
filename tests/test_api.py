from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient
from tests.fakes import StubWorkerRuntime, happy_path_llm_factory, rewrite_llm_factory

from research_report_agent.api import create_app
from research_report_agent.orchestrator import Orchestrator
from research_report_agent.storage import Database

TASK_IDS = ["task_001", "task_002", "task_003"]


async def make_client() -> tuple[AsyncClient, object]:
    database = Database.in_memory()
    await database.create_schema()
    orchestrator = Orchestrator(
        database,
        happy_path_llm_factory(TASK_IDS),
        worker_runtime=StubWorkerRuntime(),
    )
    app = create_app(database=database, orchestrator=orchestrator)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, app.state


async def test_health_endpoint() -> None:
    client, _ = await make_client()
    async with client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_create_run_validates_goal() -> None:
    client, _ = await make_client()
    async with client:
        response = await client.post("/api/runs", json={"goal": ""})

    assert response.status_code == 422


async def test_full_run_api_round_trip() -> None:
    client, state = await make_client()
    async with client:
        created = await client.post(
            "/api/runs",
            json={
                "goal": "Compare EV battery chemistries for cost and safety",
                "dimensions": ["cost", "safety"],
            },
        )
        run_id = created.json()["run_id"]
        await state.orchestrator.wait(run_id)

        run = await client.get(f"/api/runs/{run_id}")
        tasks = await client.get(f"/api/runs/{run_id}/tasks")
        attempts = await client.get(f"/api/runs/{run_id}/attempts")
        events = await client.get(f"/api/runs/{run_id}/events")
        report = await client.get(f"/api/runs/{run_id}/report")
        markdown = await client.get(f"/api/runs/{run_id}/report.md")

    assert created.status_code == 201
    assert run.json()["status"] == "complete"
    assert len(tasks.json()) == 3
    assert len(attempts.json()) == 3
    assert events.json()["events"]
    assert report.json()["guardrail_verdict"] == "allow"
    assert "## Sources" in markdown.text


async def test_list_model_providers() -> None:
    client, _ = await make_client()
    async with client:
        response = await client.get("/api/model-providers")

    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body}
    assert ids == {"openai", "deepseek", "anthropic"}
    deepseek = next(item for item in body if item["id"] == "deepseek")
    assert deepseek["base_url"] == "https://api.deepseek.com"
    assert "deepseek-v4-flash" in deepseek["models"]


async def test_get_model_config_defaults() -> None:
    client, _ = await make_client()
    async with client:
        response = await client.get("/api/model-config")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-4o-mini"
    assert body["api_key_masked"] is None


async def test_update_model_config_masks_the_key() -> None:
    client, _ = await make_client()
    async with client:
        response = await client.post(
            "/api/model-config",
            json={
                "model": "gpt-4.1",
                "base_url": "https://gateway.example.com/v1",
                "api_key": "sk-test-secret",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "gpt-4.1"
    assert body["base_url"] == "https://gateway.example.com/v1"
    assert body["api_key_masked"] is not None
    assert "sk-test-secret" not in response.text


async def test_update_model_config_switches_provider() -> None:
    client, _ = await make_client()
    async with client:
        response = await client.post(
            "/api/model-config",
            json={"provider": "anthropic", "model": "claude-opus-5", "api_key": "sk-ant-test"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-opus-5"


async def test_update_model_config_rejects_bad_base_url() -> None:
    client, _ = await make_client()
    async with client:
        response = await client.post("/api/model-config", json={"base_url": "not-a-url"})

    assert response.status_code == 400


async def test_test_model_config_without_key() -> None:
    client, _ = await make_client()
    async with client:
        response = await client.post("/api/model-config/test")

    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": "No API key configured"}


async def test_unknown_run_returns_404() -> None:
    client, _ = await make_client()
    async with client:
        response = await client.get("/api/runs/run_missing")

    assert response.status_code == 404


async def test_sse_stream_ends_after_terminal_event() -> None:
    client, state = await make_client()
    async with client:
        created = await client.post(
            "/api/runs",
            json={
                "goal": "Compare EV battery chemistries for cost and safety",
                "dimensions": ["cost", "safety"],
            },
        )
        run_id = created.json()["run_id"]
        await state.orchestrator.wait(run_id)
        response = await client.get(f"/api/runs/{run_id}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: run.phase.changed" in response.text
    assert "event: run.completed" in response.text


async def test_cancel_run() -> None:
    client, state = await make_client()
    async with client:
        created = await client.post(
            "/api/runs",
            json={"goal": "Compare technologies", "dimensions": ["cost"]},
        )
        run_id = created.json()["run_id"]
        await state.orchestrator.cancel(run_id)
        response = await client.delete(f"/api/runs/{run_id}")

    assert response.status_code == 409
    assert response.json()["detail"] == "Run is not active"


async def test_cancel_active_run_through_http() -> None:
    worker_started = asyncio.Event()

    class SlowWorkerRuntime(StubWorkerRuntime):
        async def execute_attempt(self, request, *, cancel_event=None):  # type: ignore[no-untyped-def]
            worker_started.set()
            await asyncio.sleep(30)
            raise AssertionError("Slow worker should be cancelled")

    database = Database.in_memory()
    await database.create_schema()
    orchestrator = Orchestrator(
        database,
        happy_path_llm_factory(TASK_IDS),
        worker_runtime=SlowWorkerRuntime(),
    )
    app = create_app(database=database, orchestrator=orchestrator)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/runs",
            json={"goal": "Compare technologies", "dimensions": ["cost"]},
        )
        run_id = created.json()["run_id"]

        # Wait on a signal from the worker rather than polling a fixed budget:
        # the old 100 x 10ms loop gave the run one second to reach a running
        # worker, which was enough locally but flaked on slower CI runners.
        # The orchestrator marks the task RUNNING before it invokes the runtime,
        # so once execute_attempt is entered that state is already durable.
        await asyncio.wait_for(worker_started.wait(), timeout=30)
        assert (await database.tasks.list(run_id))[0].state.value == "running"

        response = await client.delete(f"/api/runs/{run_id}")

        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
        assert (await database.tasks.list(run_id))[0].state.value == "cancelled"


async def test_restart_creates_a_new_run_and_keeps_the_original() -> None:
    client, state = await make_client()
    async with client:
        created = await client.post(
            "/api/runs",
            json={"goal": "Compare EV battery chemistries", "dimensions": ["cost"]},
        )
        run_id = created.json()["run_id"]
        await state.orchestrator.wait(run_id)

        restarted = await client.post(f"/api/runs/{run_id}/restart")
        assert restarted.status_code == 201
        body = restarted.json()
        assert body["run_id"] != run_id
        assert body["goal"] == "Compare EV battery chemistries"
        assert body["dimensions"] == ["cost"]
        await state.orchestrator.wait(body["run_id"])

        original = await client.get(f"/api/runs/{run_id}")
        assert original.status_code == 200
        assert original.json()["run_id"] == run_id


async def test_restart_rejects_a_missing_run() -> None:
    client, _ = await make_client()
    async with client:
        response = await client.post("/api/runs/run_nope/restart")

    assert response.status_code == 404


async def test_report_html_is_self_contained() -> None:
    client, state = await make_client()
    async with client:
        created = await client.post(
            "/api/runs",
            json={"goal": "Compare EV battery chemistries for cost and safety"},
        )
        run_id = created.json()["run_id"]
        await state.orchestrator.wait(run_id)

        response = await client.get(f"/api/runs/{run_id}/report.html")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "attachment" in response.headers["content-disposition"]
    body = response.text
    assert body.startswith("<!doctype html>")
    assert "<style>" in body
    # nothing may be fetched from the network when the file is opened later
    assert "<script" not in body.lower()
    assert "src=" not in body.lower()


def test_report_html_refuses_to_link_a_javascript_url() -> None:
    from types import SimpleNamespace

    from research_report_agent.report_html import render_report_html

    report = SimpleNamespace(
        title="T",
        created_at="2026-08-21",
        structured={
            "sources": [
                {"url": "javascript:alert(1)", "title": "Click me", "publisher": "p"},
                {"url": "  JavaScript:alert(2)", "title": "Sneaky", "publisher": "p"},
                {"url": "data:text/html,<script>", "title": "Data", "publisher": "p"},
                {"url": "https://ok.example/a?x=1&y=2", "publisher": "q"},
            ]
        },
    )
    out = render_report_html(report, goal="g")

    # Unsafe schemes never become an href, but their text is still shown.
    assert "javascript:" not in out.lower()
    assert "data:text/html" not in out
    assert "Click me" in out and "Sneaky" in out and "Data" in out
    # http(s) still links, and a missing title falls back to a singly-escaped URL.
    assert '<a href="https://ok.example/a?x=1&amp;y=2"' in out
    assert "&amp;amp;" not in out


async def _guided_client() -> tuple[AsyncClient, object]:
    database = Database.in_memory()
    await database.create_schema()
    orchestrator = Orchestrator(
        database,
        happy_path_llm_factory(TASK_IDS),
        worker_runtime=StubWorkerRuntime(),
    )
    app = create_app(database=database, orchestrator=orchestrator)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, app.state


async def test_guided_run_pauses_for_confirmation_before_planning() -> None:
    client, state = await _guided_client()
    async with client:
        created = await client.post(
            "/api/runs",
            json={"goal": "Compare technologies", "dimensions": ["cost"], "mode": "guided"},
        )
        run_id = created.json()["run_id"]
        await state.orchestrator.wait(run_id)

        run = (await client.get(f"/api/runs/{run_id}")).json()
        tasks = (await client.get(f"/api/runs/{run_id}/tasks")).json()

    # Parked, not running and not terminal.
    assert run["status"] == "awaiting_input"
    assert run["phase"] == "awaiting_confirmation"
    assert run["pending_gate"]["kind"] == "confirm_question"
    assert run["pending_gate"]["payload"]["rewritten_goal"]
    # Crucially: it stopped *before* spending anything on planning or research.
    assert tasks == []


async def test_a_guided_run_stops_at_both_gates_then_completes() -> None:
    client, state = await _guided_client()
    async with client:
        created = await client.post(
            "/api/runs",
            json={"goal": "Compare technologies", "mode": "guided"},
        )
        run_id = created.json()["run_id"]
        await state.orchestrator.wait(run_id)

        # Gate 1: the question.
        first = (await client.get(f"/api/runs/{run_id}")).json()
        assert first["pending_gate"]["kind"] == "confirm_question"

        await client.post(f"/api/runs/{run_id}/confirm", json={})
        await state.orchestrator.wait(run_id)

        # Gate 2: the finished report, before it is delivered.
        second = (await client.get(f"/api/runs/{run_id}")).json()
        assert second["status"] == "awaiting_input"
        assert second["phase"] == "awaiting_report_review"
        assert second["pending_gate"]["kind"] == "confirm_report"
        # The draft is already readable while parked.
        assert (await client.get(f"/api/runs/{run_id}/report")).status_code == 200

        accepted = await client.post(f"/api/runs/{run_id}/confirm", json={"decision": "accept"})
        await state.orchestrator.wait(run_id)
        run = (await client.get(f"/api/runs/{run_id}")).json()

    assert accepted.status_code == 200
    assert run["status"] == "complete"
    assert run["pending_gate"] is None


async def test_rewriting_a_report_reuses_the_findings_without_researching_again() -> None:
    database = Database.in_memory()
    await database.create_schema()
    orchestrator = Orchestrator(
        database,
        rewrite_llm_factory(TASK_IDS),
        worker_runtime=StubWorkerRuntime(),
    )
    app = create_app(database=database, orchestrator=orchestrator)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    state = app.state
    async with client:
        created = await client.post(
            "/api/runs",
            json={"goal": "Compare technologies", "mode": "guided"},
        )
        run_id = created.json()["run_id"]
        await state.orchestrator.wait(run_id)
        await client.post(f"/api/runs/{run_id}/confirm", json={})
        await state.orchestrator.wait(run_id)

        attempts_before = len((await client.get(f"/api/runs/{run_id}/attempts")).json())
        searches_before = (await client.get(f"/api/runs/{run_id}")).json()["usage"]["tool_calls"]

        await client.post(
            f"/api/runs/{run_id}/confirm",
            json={"decision": "rewrite", "instruction": "Make it much shorter"},
        )
        await state.orchestrator.wait(run_id)

        run = (await client.get(f"/api/runs/{run_id}")).json()
        attempts_after = len((await client.get(f"/api/runs/{run_id}/attempts")).json())

    # A rewrite costs a synthesis call and nothing else: no new attempts, no
    # new tool calls, and it parks again for review rather than auto-delivering.
    assert attempts_after == attempts_before
    assert run["usage"]["tool_calls"] == searches_before
    assert run["pending_gate"]["kind"] == "confirm_report"
    assert run["pending_gate"]["payload"]["revised"] is True


async def test_confirming_with_an_edited_question_uses_the_edit() -> None:
    client, state = await _guided_client()
    async with client:
        created = await client.post(
            "/api/runs",
            json={"goal": "Compare technologies", "mode": "guided"},
        )
        run_id = created.json()["run_id"]
        await state.orchestrator.wait(run_id)

        await client.post(
            f"/api/runs/{run_id}/confirm",
            json={"goal": "Compare only lithium iron phosphate cells", "dimensions": ["cost"]},
        )
        await state.orchestrator.wait(run_id)
        run = (await client.get(f"/api/runs/{run_id}")).json()

    assert run["goal"] == "Compare only lithium iron phosphate cells"
    assert run["dimensions"] == ["cost"]


async def test_confirm_rejects_a_run_with_no_open_gate() -> None:
    client, state = await make_client()
    async with client:
        created = await client.post("/api/runs", json={"goal": "Compare technologies"})
        run_id = created.json()["run_id"]
        await state.orchestrator.wait(run_id)
        response = await client.post(f"/api/runs/{run_id}/confirm", json={})

    assert response.status_code == 409
    assert response.json()["detail"] == "Run is not waiting for input"


async def test_autonomous_runs_are_not_gated() -> None:
    client, state = await make_client()
    async with client:
        created = await client.post("/api/runs", json={"goal": "Compare technologies"})
        run_id = created.json()["run_id"]
        await state.orchestrator.wait(run_id)
        run = (await client.get(f"/api/runs/{run_id}")).json()

    assert run["status"] == "complete"
    assert run["pending_gate"] is None


async def test_deleting_a_run_removes_its_whole_record() -> None:
    client, state = await make_client()
    async with client:
        created = await client.post(
            "/api/runs",
            json={"goal": "Compare technologies", "dimensions": ["cost"]},
        )
        run_id = created.json()["run_id"]
        await state.orchestrator.wait(run_id)

        # It has real children before the delete.
        assert (await client.get(f"/api/runs/{run_id}/tasks")).json()
        assert (await client.get(f"/api/runs/{run_id}/attempts")).json()
        assert (await client.get(f"/api/runs/{run_id}/events")).json()["events"]
        assert (await client.get(f"/api/runs/{run_id}/report")).status_code == 200

        response = await client.delete(f"/api/runs/{run_id}/permanent")

        assert response.status_code == 204
        assert (await client.get(f"/api/runs/{run_id}")).status_code == 404
        assert (await client.get(f"/api/runs/{run_id}/report")).status_code == 404
        assert run_id not in [item["run_id"] for item in (await client.get("/api/runs")).json()]

    # Nothing is left keyed by the run in the orchestrator's memory either.
    assert run_id not in state.orchestrator._agents
    assert run_id not in state.orchestrator._usage
    assert run_id not in state.orchestrator._budgets
    assert run_id not in state.orchestrator._event_counters


async def test_deleting_refuses_while_a_run_is_still_active() -> None:
    worker_started = asyncio.Event()

    class SlowWorkerRuntime(StubWorkerRuntime):
        async def execute_attempt(self, request, *, cancel_event=None):  # type: ignore[no-untyped-def]
            worker_started.set()
            await asyncio.sleep(30)
            raise AssertionError("Slow worker should be cancelled")

    database = Database.in_memory()
    await database.create_schema()
    orchestrator = Orchestrator(
        database,
        happy_path_llm_factory(TASK_IDS),
        worker_runtime=SlowWorkerRuntime(),
    )
    app = create_app(database=database, orchestrator=orchestrator)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/runs", json={"goal": "Compare technologies"})
        run_id = created.json()["run_id"]
        await asyncio.wait_for(worker_started.wait(), timeout=30)

        blocked = await client.delete(f"/api/runs/{run_id}/permanent")
        assert blocked.status_code == 409

        # Stopping it first makes the delete allowed.
        await client.delete(f"/api/runs/{run_id}")
        assert (await client.delete(f"/api/runs/{run_id}/permanent")).status_code == 204


async def test_deleting_an_unknown_run_is_a_404() -> None:
    client, _ = await make_client()
    async with client:
        response = await client.delete("/api/runs/run_nope/permanent")

    assert response.status_code == 404


async def test_a_run_parked_at_a_gate_can_be_stopped() -> None:
    """A gated run is not RUNNING, but it is still open and must be stoppable.

    It holds planned tasks and resumes the moment it is answered, so leaving
    delete as the only way out of a gate would be wrong.
    """
    client, state = await _guided_client()
    async with client:
        created = await client.post(
            "/api/runs",
            json={"goal": "Compare technologies", "mode": "guided"},
        )
        run_id = created.json()["run_id"]
        await state.orchestrator.wait(run_id)
        assert (await client.get(f"/api/runs/{run_id}")).json()["status"] == "awaiting_input"

        stopped = await client.delete(f"/api/runs/{run_id}")

        assert stopped.status_code == 200
        assert stopped.json()["status"] == "cancelled"

        # And it stays stopped -- confirming it afterwards is refused.
        assert (await client.post(f"/api/runs/{run_id}/confirm", json={})).status_code == 409
