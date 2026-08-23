# 2026-08-20 — Rebuild: real LLM agents

## Status before this change

The fullstack scaffold from the previous milestones (contracts, LangGraph orchestrator,
FastAPI service, SQLite persistence, React dashboard) was real, working infrastructure.
Every "agent" wired into it, however, was 100% deterministic and templated:

- `agents/planner.py` returned hardcoded task-template strings.
- `agents/critic.py` was `if status == "completed" and findings and sources: accept`.
- `agents/guardrail.py` matched a fixed keyword/regex list.
- `agents/synthesizer.py` filled in boilerplate sentences.
- `worker_runtime.py` / `tools.py` matched every query against **three hardcoded fake
  documents about EV batteries** — every research goal produced EV-battery-flavored
  output regardless of topic. There was no `OPENAI_API_KEY` or model-client code
  anywhere in `src/`.

The README's claim ("deterministic local agents, no model credential required") was
accurate but hid the real problem: the system could not research anything.

## What changed

- Added `config.py` (file + env-backed model settings, mirrors the sibling `sentinel`
  project's `config.ts`) and `llm.py` (an async OpenAI-compatible client with the
  schema-repair retry policy this repo's own design doc always specified but never
  implemented).
- Rewrote `tools.py`: `web_search` now queries DuckDuckGo's keyless HTML endpoint for
  real results; `fetch_page` performs a real, size-capped, redirect-revalidating fetch
  and strips real HTML to text; `calculator` was already real and is unchanged.
- Rewrote `worker_runtime.py` as the bounded ReAct loop the design doc described in
  §18.2: the model chooses one tool call at a time from real observations, and a final
  model call extracts findings — accepted only when they cite a URL the worker actually
  saw, so citations cannot be invented.
- Rewrote `agents/planner.py`, `agents/critic.py`, `agents/guardrail.py` (both intake
  and final-output), and `agents/synthesizer.py` to call the model, validated by the
  same Pydantic contracts as before (`ResearchPlan`, `CriticReview`, `GuardrailReview`,
  `ResearchReport`). The synthesizer keeps source de-duplication and citation-map
  construction as deterministic code — that is data plumbing, not synthesis.
- `orchestrator.py`: agents are now built lazily per run from a `llm_factory`, so
  `create_app()`/`import research_report_agent.main` never requires an API key —
  configuring one through the dashboard and starting a run does, matching the sibling
  `sentinel` project's "lazy client" pattern.
- Added a `⚙ Model API` settings panel to the dashboard and `GET/POST /api/model-config`
  + `POST /api/model-config/test` endpoints, mirroring `sentinel`'s settings UX.
- Test suite: added a `FakeLLMClient` test double (`tests/fakes.py`) so every agent,
  the worker loop, and the orchestrator's scheduling/retry/cancellation logic are still
  tested fast and offline; `tools.py` tests moved from asserting fixed fake results to
  a mocked `httpx` transport. Verified live (outside the test suite) against the real
  DuckDuckGo endpoint and real fetched pages for a non-EV-battery query.

## Why

Continuing to build product features (Milestone F3/F4, evaluation, deployment) on top
of a simulation that always returns the same three EV-battery documents would not have
been a real research agent — it would have been a demo of one. The MVP acceptance
criteria in `docs/spec/design.md` §21 (a cited report from real evidence, retries on
invalid output, a guardrail that can actually refuse) can only be judged once the
system is actually calling a model and the real web.

## Not done here

- No new search provider abstraction beyond DuckDuckGo — the design doc's MVP scope
  never required more than one, and building a multi-provider plugin system nobody
  asked for would be premature.
- No changes to the LangGraph graph topology, scheduling algorithm, persistence schema,
  or frontend routes/pages — those were already real and are unaffected by this change.
