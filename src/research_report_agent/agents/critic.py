"""LLM-backed quality critic agent."""

from __future__ import annotations

from research_report_agent.contracts import CriticReview, WorkerResult
from research_report_agent.llm import LLMClient

_VERDICTS = '"accept"|"revise"|"replan"|"degrade"|"fail"'

_SYSTEM = f"""You are the quality critic for a multi-agent research system. Review \
worker research results for RESEARCH QUALITY only — coverage, evidence quality, \
source quality, consistency, confidence, and comparability. You are not a safety \
reviewer; leave safety judgments to the guardrail.

For each task result, decide a verdict:
- "accept": findings are relevant, sourced, and meet the task's success criteria.
- "revise": findings are partial or weak; you MUST include a follow_up task asking a \
narrower, bounded question (max_tool_calls <= 3) that closes the specific gap.
- "replan" or "degrade": only for a task that cannot be salvaged with one follow-up.

Set overall_verdict to "fail" only when there is truly no usable evidence in ANY task; \
otherwise "accept" if every task_review accepts, else "revise".

Respond with JSON matching this shape exactly. "follow_up" is only allowed (and then \
required) when verdict is "revise" — omit it (null) for every other verdict. Leave \
cross_task_issues/missing_dimensions/contradictions as [] when there's nothing to report:
{{"review_id": "...", "run_id": "...", "overall_verdict": {_VERDICTS},
 "task_reviews": [{{"task_id": "...", "verdict": {_VERDICTS},
   "reason": "...", "follow_up": null}}],
 "cross_task_issues": [{{"issue": "...", "affected_task_ids": ["..."],
   "severity": "low"|"medium"|"high", "recommended_action": {_VERDICTS}}}],
 "missing_dimensions": [], "contradictions": []}}
A "revise" task_review's follow_up must look like: {{"task_id": "...", \
"parent_task_id": "...", "question": "...", "constraints": ["..."], "max_tool_calls": 3}}."""


class Critic:
    """Review worker results and emit a structured graph action."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def review(self, run_id: str, results: list[WorkerResult]) -> CriticReview:
        user = f"run_id: {run_id}\n\nWorker results:\n" + "\n\n".join(
            result.model_dump_json(indent=2) for result in results
        )
        return await self.llm.complete_structured(system=_SYSTEM, user=user, schema=CriticReview)


__all__ = ["Critic"]
