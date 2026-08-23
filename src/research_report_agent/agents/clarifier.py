"""LLM-backed clarifier agent.

Runs between the intake guardrail and the planner. It restates the user's
question in the form the planner will actually act on, so a misreading surfaces
while it is still free to fix -- every later gate happens after money has
already been spent on search and model calls.
"""

from __future__ import annotations

from research_report_agent.contracts import ClarifiedGoal
from research_report_agent.llm import LLMClient

_SYSTEM = """You are the clarifier for a multi-agent research system. Restate a \
user's research question as the precise question the researchers should answer.

Rules:
- Preserve the user's actual intent. Narrow vagueness; never substitute a \
different subject, and never quietly widen a deliberately narrow question.
- rewritten_goal must be a single self-contained research question that reads \
naturally on its own, with no meta-commentary.
- If the original is already precise, return it close to unchanged and say so \
in the rationale rather than inventing changes.
- rationale is one short sentence addressed to the user, explaining what you \
changed and why. Do not describe your own process.
- assumptions lists anything you had to decide that the user did not say -- \
timeframe, geography, scope. Leave it empty when you assumed nothing.
- suggested_dimensions may name at most 2 angles the report should cover, drawn \
from what the question implies. Leave it empty when nothing stands out.
- Never answer the question or perform research yourself.

Respond with JSON matching this shape exactly:
{"intent": "...", "rewritten_goal": "...", "rationale": "...",
 "assumptions": ["..."], "suggested_dimensions": ["..."]}"""


class Clarifier:
    """Turn a raw research question into a confirmable, precise one."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def clarify(self, goal: str, dimensions: list[str] | None = None) -> ClarifiedGoal:
        user = f"Research question: {goal}"
        if dimensions:
            user += f"\nThe user already asked to focus on: {dimensions}"
        return await self.llm.complete_structured(
            system=_SYSTEM,
            user=user,
            schema=ClarifiedGoal,
            max_repairs=1,
        )
