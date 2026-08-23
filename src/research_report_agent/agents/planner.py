"""LLM-backed planner agent."""

from __future__ import annotations

from research_report_agent.contracts import ResearchPlan
from research_report_agent.llm import LLMClient

_SYSTEM = """You are the planner for a multi-agent research system. Convert a broad \
research goal into 3-6 discrete, non-overlapping research tasks.

Rules:
- Produce between 3 and 6 tasks.
- Each task must have a unique task_id (e.g. "task_001", "task_002", ...).
- Tasks must be discrete research questions, not vague topic labels.
- Every task needs at least one success_criteria entry and required_tools drawn only \
from ["web_search", "fetch_page", "calculator"]; almost every task needs "web_search".
- priority must be "low", "medium", or "high".
- dependencies must reference only earlier task_ids in this same plan and must never \
be circular; most tasks should depend on an initial entity-identification task.
- Cover every required dimension the user asked for.
- Do not perform research yourself, do not fabricate findings, and do not create a \
task whose success cannot later be judged from evidence.

Respond with JSON matching this shape exactly:
{"plan_id": "plan_001", "objective": "...", "tasks": [
  {"task_id": "task_001", "question": "...", "success_criteria": ["..."],
   "required_tools": ["web_search"], "priority": "high", "dependencies": []}
]}"""


class Planner:
    """Turn a research goal into a validated, dependency-aware plan."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def create_plan(self, goal: str, dimensions: list[str]) -> ResearchPlan:
        user = f"Research goal: {goal}\nRequired dimensions: {dimensions or ['(none specified)']}"
        return await self.llm.complete_structured(
            system=_SYSTEM,
            user=user,
            schema=ResearchPlan,
            max_repairs=2,
        )


__all__ = ["Planner"]
