"""LLM-backed synthesizer agent.

Source de-duplication and citation-map construction stay deterministic, code-owned
logic — that is data plumbing that must be correct by construction. Only the report's
prose (executive summary, section text, comparison table, conclusions) is written by
the model, and only from the accepted findings/sources it is handed — see
``docs/spec/design.md`` §6.5 ("must not invent new facts").
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from research_report_agent.contracts import (
    Finding,
    ReportConclusion,
    ReportSection,
    ResearchReport,
    Source,
    WorkerResult,
)
from research_report_agent.llm import LLMClient
from research_report_agent.runtime_contracts import ReportDocument


def _strip_finding_id_leakage(text: str, finding_ids: list[str]) -> str:
    """Remove any internal finding_id token that leaked into rendered prose.

    finding_ids look like "task_002_finding_013" and are meant only for the JSON
    "basis" field — never for prose. A model that ignores that instruction (observed
    live: it copied the "(id: ...)" label straight into report text as if it were a
    citation) must not be able to put an unresolvable token in front of a reader, so
    this is enforced in code rather than trusted to the prompt alone.
    """

    if not finding_ids:
        return text
    pattern = re.compile(
        r"[\[(]?\s*(?:id:\s*)?(?:" + "|".join(re.escape(fid) for fid in finding_ids) + r")\s*[\])]?"
    )
    cleaned = pattern.sub(" ", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    cleaned = cleaned.strip()
    return cleaned or text


class _DraftConclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conclusion: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    basis: list[str] = Field(min_length=1)


class _DraftSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(min_length=1)
    markdown: str = Field(min_length=1)


class _ReportDraft(BaseModel):
    """What the model writes; the source list and citation map are built in code."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    executive_summary: str = Field(min_length=1)
    sections: list[_DraftSection] = Field(min_length=1)
    comparison_table_markdown: str | None = None
    conclusions: list[_DraftConclusion] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)


_SYSTEM = """You are the synthesizer for a multi-agent research system. Write a \
coherent, cited final report from ONLY the accepted findings and sources given to you.

Rules:
- Use only the provided findings and sources; never invent new facts or citations.
- Every conclusion's "basis" must list finding_id values (given as "id: ..." below) \
taken from the provided findings — but finding_id values are internal bookkeeping \
and must NEVER appear anywhere in the report prose (executive_summary, sections, \
comparison table). They belong only in the JSON "basis" array.
- The ONLY inline citation marker allowed in prose is one of the numbered source \
labels from the Sources list below, e.g. "...as shown [1]." Never write a finding_id \
like "task_002_finding_013" as a citation — it is not a citation, and a reader would \
have no way to resolve it.
- Explain unresolved contradictions and uncertainty; separate evidence from opinion.
- Include a comparison table when the goal is comparative, else set it to null.
- When the user named required dimensions, give each one its own section (or its own \
column in the comparison table when comparing options), and say so plainly in \
"limitations" if the evidence does not actually cover one of them.
- Frame conclusions as evidence-based tradeoffs, never as personalized purchasing, \
medical, legal, financial, or safety advice.

Respond with JSON: {"title": "...", "executive_summary": "...", \
"sections": [{"heading": "...", "markdown": "..."}], \
"comparison_table_markdown": "... or null", \
"conclusions": [{"conclusion": "...", "confidence": 0.0, "basis": ["finding_id"]}], \
"limitations": ["..."]}"""


class Synthesizer:
    """Combine accepted worker findings into a cited report."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def synthesize(
        self,
        *,
        run_id: str,
        goal: str,
        results: list[WorkerResult],
        dimensions: list[str] | None = None,
        revision_instruction: str | None = None,
    ) -> ReportDocument:
        findings, sources = self._merge_evidence(results)
        if not findings or not sources:
            raise ValueError("Cannot synthesize a report without accepted evidence")

        citation_map = {f"[{i}]": source.source_id for i, source in enumerate(sources, start=1)}
        draft = await self.llm.complete_structured(
            system=_SYSTEM,
            user=self._prompt(
                goal,
                findings,
                sources,
                citation_map,
                dimensions or [],
                revision_instruction,
            ),
            schema=_ReportDraft,
        )

        accepted_ids = [finding.finding_id for finding in findings]
        accepted_id_set = set(accepted_ids)
        conclusions = [
            ReportConclusion(
                conclusion=_strip_finding_id_leakage(item.conclusion, accepted_ids),
                confidence=item.confidence,
                basis=[fid for fid in item.basis if fid in accepted_id_set] or accepted_ids[:1],
            )
            for item in draft.conclusions
        ]

        report = ResearchReport(
            report_id=f"{run_id}_report_001",
            run_id=run_id,
            title=draft.title,
            executive_summary=_strip_finding_id_leakage(draft.executive_summary, accepted_ids),
            sections=[
                ReportSection(
                    heading=section.heading,
                    markdown=_strip_finding_id_leakage(section.markdown, accepted_ids),
                )
                for section in draft.sections
            ],
            comparison_table_markdown=(
                _strip_finding_id_leakage(draft.comparison_table_markdown, accepted_ids)
                if draft.comparison_table_markdown
                else None
            ),
            conclusions=conclusions,
            limitations=draft.limitations,
            accepted_finding_ids=accepted_ids,
            sources=sources,
            citation_map=citation_map,
        )
        return ReportDocument(
            report_id=report.report_id,
            run_id=run_id,
            title=report.title,
            markdown=self._markdown(report),
            structured=report.model_dump(mode="json"),
            guardrail_verdict="allow",
        )

    def _prompt(
        self,
        goal: str,
        findings: list[Finding],
        sources: list[Source],
        citation_map: dict[str, str],
        dimensions: list[str],
        revision_instruction: str | None = None,
    ) -> str:
        source_lines = "\n".join(
            f"{label}: {source.title} — {source.publisher} ({source.url})"
            for label, source in zip(citation_map.keys(), sources, strict=True)
        )
        finding_lines = "\n".join(
            f"- (id: {finding.finding_id}) {finding.claim} — evidence: {finding.evidence} "
            f"(sources: {finding.source_ids}, confidence: {finding.confidence:.2f})"
            for finding in findings
        )
        dimension_line = (
            f"Required dimensions (give each its own section): {dimensions}\n\n"
            if dimensions
            else ""
        )
        revision_line = (
            "The reader has already seen a draft built from exactly these findings and "
            f"asked for this change: {revision_instruction}\n"
            "Rewrite the report accordingly. You have no new evidence -- work only with "
            "the findings below, and say so in limitations if the request cannot be met "
            "from them.\n\n"
            if revision_instruction
            else ""
        )
        return (
            f"Research goal: {goal}\n\n"
            f"{revision_line}"
            f"{dimension_line}"
            f"Sources:\n{source_lines}\n\n"
            f"Accepted findings:\n{finding_lines}"
        )

    def _merge_evidence(
        self,
        results: list[WorkerResult],
    ) -> tuple[list[Finding], list[Source]]:
        findings: list[Finding] = []
        sources: list[Source] = []
        source_id_by_task: dict[tuple[str, str], str] = {}
        source_id_by_url: dict[str, str] = {}

        for result in results:
            for source in result.sources:
                if source.url in source_id_by_url:
                    global_id = source_id_by_url[source.url]
                else:
                    global_id = f"{result.task_id}_{source.source_id}"
                    source_id_by_url[source.url] = global_id
                    sources.append(source.model_copy(update={"source_id": global_id}))
                source_id_by_task[(result.task_id, source.source_id)] = global_id

            for finding in result.findings:
                mapped_ids = [
                    source_id_by_task[(result.task_id, source_id)]
                    for source_id in finding.source_ids
                ]
                findings.append(
                    finding.model_copy(
                        update={
                            "finding_id": f"{result.task_id}_{finding.finding_id}",
                            "source_ids": mapped_ids,
                        }
                    )
                )

        return findings, sources

    def _markdown(self, report: ResearchReport) -> str:
        lines = [f"# {report.title}", "", report.executive_summary, ""]
        if report.comparison_table_markdown:
            lines.extend(["## Comparison", "", report.comparison_table_markdown, ""])
        for section in report.sections:
            lines.extend([f"## {section.heading}", "", section.markdown, ""])
        lines.extend(["## Conclusions", ""])
        for conclusion in report.conclusions:
            lines.append(f"- {conclusion.conclusion} _(confidence: {conclusion.confidence:.2f})_")
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {item}" for item in report.limitations)
        lines.extend(["", "## Sources", ""])
        for label, source_id in report.citation_map.items():
            source = next(item for item in report.sources if item.source_id == source_id)
            lines.append(f"- {label}: {source.title} — {source.publisher} — {source.url}")
        return "\n".join(lines) + "\n"


__all__ = ["Synthesizer"]
