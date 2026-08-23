"""Render a stored report as a standalone, self-contained HTML document.

The file has to survive being emailed, dropped in a shared folder, or opened
years from now with no server around, so everything -- styles included -- is
inlined and there are no external requests.
"""

from __future__ import annotations

import html
import re
from typing import Any

_STYLES = """
:root{color-scheme:light dark;--paper:#fcfbf9;--ink:#14181f;--ink-2:#454c59;
--ink-3:#6e7684;--line:#e5e1da;--accent:#1f3a6e;--warn:#8a5d12}
@media (prefers-color-scheme:dark){:root{--paper:#1a1e25;--ink:#e7e9ed;
--ink-2:#a8aeba;--ink-3:#7a8290;--line:#2c323c;--accent:#86adec;--warn:#d3a34e}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font-family:Georgia,"Times New Roman",serif;font-size:17px;line-height:1.68}
.wrap{max-width:44rem;margin:0 auto;padding:56px 24px 80px}
h1{font-size:2rem;line-height:1.15;letter-spacing:-.015em;margin:0 0 6px}
.meta{font-family:ui-sans-serif,system-ui,sans-serif;font-size:.78rem;
letter-spacing:.04em;text-transform:uppercase;color:var(--ink-3);
margin:0 0 28px;padding-bottom:20px;border-bottom:1px solid var(--line)}
.lead{font-size:1.12rem;color:var(--ink-2);margin:0 0 30px}
h2{font-size:1.3rem;letter-spacing:-.01em;margin:34px 0 10px}
p{margin:0 0 14px}
ul,ol{padding-left:24px;margin:0 0 14px}
a{color:var(--accent)}
sup a{font-family:ui-monospace,monospace;font-size:.62rem;text-decoration:none}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;margin:0 0 18px}
table{border-collapse:collapse;width:100%;font-family:ui-sans-serif,system-ui,sans-serif;
font-size:.88rem;min-width:30rem}
th,td{padding:9px 13px;text-align:left;border-bottom:1px solid var(--line)}
th{font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3)}
tr:last-child td{border-bottom:none}
td:first-child{font-weight:600}
.concl{list-style:none;padding:0}
.concl li{display:flex;gap:14px;margin-bottom:12px}
.conf{font-family:ui-monospace,monospace;font-size:.7rem;color:var(--ink-3);
flex:none;width:3rem;padding-top:5px}
.limits li{color:var(--ink-2);font-size:.95rem}
.src{list-style:none;padding:0;font-family:ui-sans-serif,system-ui,sans-serif}
.src li{display:flex;gap:12px;padding:11px 0;border-bottom:1px solid var(--line);
font-size:.9rem}
.src li:last-child{border-bottom:none}
.src .n{font-family:ui-monospace,monospace;font-size:.7rem;color:var(--ink-3);
flex:none;width:1.6rem;padding-top:3px}
.src small{display:block;color:var(--ink-3);margin-top:3px}
footer{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);
font-family:ui-sans-serif,system-ui,sans-serif;font-size:.75rem;color:var(--ink-3)}
@media print{body{background:#fff}.wrap{padding:0}}
"""

_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])")
_BULLET = re.compile(r"^[-*]\s+")
_NUMBERED = re.compile(r"^\d+[.)]\s+")
_SAFE_SCHEMES = ("http://", "https://")


def _safe_href(raw: str) -> str | None:
    """Return the URL only when it is safe to make into a live link.

    Escaping stops an attribute breakout but not the scheme, so a source URL of
    ``javascript:...`` would otherwise render as a clickable href. Source URLs
    come from model output and fetched web content, and this document is meant
    to be emailed and opened offline, so anything that is not plain http(s)
    stays inert text.
    """
    candidate = raw.strip()
    return candidate if candidate.lower().startswith(_SAFE_SCHEMES) else None


def _inline(text: str, citations: int) -> str:
    """Escape first, then re-introduce only the markup we chose to support."""
    out: list[str] = []
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append(f"<strong>{html.escape(part[2:-2])}</strong>")
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
        elif (match := re.fullmatch(r"\[(\d+)\]", part)) and 1 <= int(match.group(1)) <= citations:
            n = match.group(1)
            out.append(f'<sup><a href="#s{n}">[{n}]</a></sup>')
        else:
            out.append(html.escape(part))
    return "".join(out)


def _prose(text: str, citations: int) -> str:
    blocks: list[str] = []
    for block in re.split(r"\n{2,}", text.strip()):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        if all(_BULLET.match(line) for line in lines):
            items = "".join(
                "<li>" + _inline(_BULLET.sub("", line), citations) + "</li>" for line in lines
            )
            blocks.append(f"<ul>{items}</ul>")
        elif all(_NUMBERED.match(line) for line in lines):
            items = "".join(
                "<li>" + _inline(_NUMBERED.sub("", line), citations) + "</li>" for line in lines
            )
            blocks.append(f"<ol>{items}</ol>")
        else:
            blocks.append(f"<p>{_inline(' '.join(lines), citations)}</p>")
    return "".join(blocks)


def _table(markdown: str, citations: int) -> str:
    lines = [line.strip() for line in markdown.strip().split("\n") if line.strip()]
    if len(lines) < 2 or not re.fullmatch(r"[\s|:-]+", lines[1]):
        return f"<pre>{html.escape(markdown)}</pre>"

    def cells(line: str) -> list[str]:
        return [cell.strip() for cell in line.strip("|").split("|")]

    head = "".join(f"<th>{_inline(cell, citations)}</th>" for cell in cells(lines[0]))
    body = "".join(
        "<tr>" + "".join(f"<td>{_inline(cell, citations)}</td>" for cell in cells(line)) + "</tr>"
        for line in lines[2:]
    )
    return (
        '<div class="tablewrap"><table>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody>"
        "</table></div>"
    )


def render_report_html(report: Any, *, goal: str = "") -> str:
    """Build the full HTML document for a stored report."""
    structured = report.structured if isinstance(report.structured, dict) else {}
    sources = structured.get("sources") or []
    citations = len(sources)
    title = html.escape(report.title or "Research report")

    parts: list[str] = [f"<h1>{title}</h1>"]
    created = str(report.created_at)[:10] if report.created_at else ""
    meta = " · ".join(filter(None, [created, f"{citations} sources" if citations else ""]))
    if meta:
        parts.append(f'<p class="meta">{html.escape(meta)}</p>')
    if goal:
        parts.append(f'<p class="lead">{html.escape(goal)}</p>')

    if summary := structured.get("executive_summary"):
        parts.append(f'<div class="lead">{_prose(str(summary), citations)}</div>')

    if table := structured.get("comparison_table_markdown"):
        parts.append("<h2>Comparison</h2>")
        parts.append(_table(str(table), citations))

    for section in structured.get("sections") or []:
        heading = html.escape(str(section.get("heading", "")))
        parts.append(f"<h2>{heading}</h2>")
        parts.append(_prose(str(section.get("markdown", "")), citations))

    if conclusions := structured.get("conclusions"):
        parts.append("<h2>Conclusions</h2><ul class='concl'>")
        for item in conclusions:
            confidence = float(item.get("confidence", 0) or 0)
            parts.append(
                f'<li><span class="conf">{confidence * 100:.0f}%</span>'
                f"<span>{_inline(str(item.get('conclusion', '')), citations)}</span></li>"
            )
        parts.append("</ul>")

    if limitations := structured.get("limitations"):
        items = "".join(f"<li>{html.escape(str(item))}</li>" for item in limitations)
        parts.append(f"<h2>Limitations</h2><ul class='limits'>{items}</ul>")

    if sources:
        parts.append("<h2>Sources</h2><ol class='src'>")
        for index, source in enumerate(sources, start=1):
            raw_url = str(source.get("url", ""))
            # Escape the label once, from the raw URL -- not from the escaped one.
            label = html.escape(str(source.get("title") or raw_url))
            href = _safe_href(raw_url)
            link = f'<a href="{html.escape(href)}" rel="noreferrer">{label}</a>' if href else label
            parts.append(
                f'<li id="s{index}"><span class="n">[{index}]</span><span>{link}'
                f"<small>{html.escape(str(source.get('publisher', '')))}</small></span></li>"
            )
        parts.append("</ol>")

    parts.append(
        "<footer>Generated by the Research &amp; Report Agent. "
        "Every claim above is traceable to a numbered source.</footer>"
    )

    return (
        "<!doctype html>\n"
        f'<html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title><style>{_STYLES}</style></head>"
        f'<body><div class="wrap">{"".join(parts)}</div></body></html>'
    )
