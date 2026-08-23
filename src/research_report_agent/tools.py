"""Bounded tool layer for worker agents.

Real, network-backed tools with the safety controls from ``docs/spec/design.md`` §9/§19:
``web_search`` uses DuckDuckGo's keyless HTML endpoint (no API key required to research
anything), ``fetch_page`` blocks private/loopback/link-local/reserved addresses and
revalidates every redirect hop, and ``calculator`` evaluates arithmetic without ``eval``.
"""

from __future__ import annotations

import ast
import asyncio
import ipaddress
import math
import operator
import re
import socket
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from research_report_agent import __version__
from research_report_agent.runtime_contracts import ToolRequest, ToolResult, utc_now

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_USER_AGENT = (
    f"Mozilla/5.0 (compatible; research-report-agent/{__version__}; "
    "+https://github.com/finnhll/research-agent-practice)"
)
_MAX_RESULTS = 5
_MAX_REDIRECTS = 3
_MAX_RESPONSE_BYTES = 1_500_000
_MAX_CONTENT_CHARS = 8_000
_ALLOWED_CONTENT_TYPES = {"text/html", "text/plain"}

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class _TextExtractor(HTMLParser):
    """Strip an HTML document down to visible text (stdlib only, no exec)."""

    _SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._title: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title.append(data)
        if not self._skip_depth:
            text = data.strip()
            if text:
                self._chunks.append(text)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._chunks)).strip()

    def title(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._title)).strip()


def _html_to_text(document: str) -> tuple[str, str]:
    parser = _TextExtractor()
    parser.feed(document)
    return parser.text(), parser.title()


class _DuckDuckGoResultParser(HTMLParser):
    """Extract (title, href, snippet) result rows from a DDG HTML results page."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._pending: dict[str, str] | None = None
        self._capture: str | None = None

    def _flush(self) -> None:
        if self._pending and self._pending.get("href") and self._pending.get("title"):
            self.results.append(self._pending)
        self._pending = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_dict = dict(attrs)
        classes = set((attrs_dict.get("class") or "").split())
        if "result__a" in classes:
            self._flush()
            self._pending = {"href": attrs_dict.get("href") or "", "title": "", "snippet": ""}
            self._capture = "title"
        elif "result__snippet" in classes and self._pending is not None:
            self._capture = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._capture = None

    def handle_data(self, data: str) -> None:
        if self._capture and self._pending is not None:
            self._pending[self._capture] += data

    def close(self) -> None:
        self._flush()
        super().close()


def _resolve_ddg_href(href: str) -> str | None:
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [None])[0]
        return target or None
    if parsed.scheme in {"http", "https"}:
        return href
    return None


class ToolExecutor:
    """Execute typed tool requests with validation and bounded, real behavior."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.call_count = 0
        self.search_count = 0
        self._transport = transport
        self._lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=10.0,
            follow_redirects=False,
            headers={"User-Agent": _USER_AGENT},
        )

    async def execute(self, request: ToolRequest) -> ToolResult:
        started_at = utc_now()
        async with self._lock:
            self.call_count += 1

        handler = {
            "web_search": self._web_search,
            "fetch_page": self._fetch_page,
            "calculator": self._calculator,
        }.get(request.tool)

        if handler is None:
            return self._error(request, "unsupported tool", started_at)

        try:
            output = await handler(request.input)
            status = "success" if output.get("status") != "error" else "error"
            output.pop("status", None)
            error = output.pop("error", None)
            if output.get("blocked"):
                status = "blocked"
                output.pop("blocked")
            return ToolResult(
                request_id=request.request_id,
                attempt_id=request.attempt_id,
                tool=request.tool,
                status=status,
                output=output,
                error=error,
                started_at=started_at,
                completed_at=utc_now(),
            )
        except Exception as exc:  # Tool boundaries must fail closed.
            return self._error(request, str(exc), started_at)

    async def _web_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = payload.get("query")
        if not isinstance(query, str) or not query.strip():
            return {"status": "error", "error": "query is required"}

        async with self._lock:
            self.search_count += 1

        try:
            async with self._client() as client:
                response = await client.get(_SEARCH_URL, params={"q": query})
        except httpx.HTTPError as exc:
            return {"status": "error", "error": f"search request failed: {exc}"}

        if response.status_code >= 400:
            return {
                "status": "error",
                "error": f"search request failed: HTTP {response.status_code}",
            }

        parser = _DuckDuckGoResultParser()
        parser.feed(response.text)
        parser.close()

        results = []
        for row in parser.results[:_MAX_RESULTS]:
            url = _resolve_ddg_href(row["href"])
            if not url:
                continue
            title = unescape(row["title"]).strip()
            snippet = unescape(row["snippet"]).strip()
            if not title:
                continue
            results.append(
                {
                    "title": title,
                    "url": url,
                    "publisher": urlparse(url).hostname or "unknown",
                    "snippet": snippet,
                }
            )

        return {"query": query, "results": results}

    async def _check_public_host(self, hostname: str, port: int) -> str | None:
        """Return an error message if the host resolves to a non-public address."""

        try:
            addresses = await asyncio.get_running_loop().getaddrinfo(
                hostname,
                port,
                type=socket.SocketKind.SOCK_STREAM,
            )
        except OSError as exc:
            return f"could not resolve host: {exc}"

        for _family, _type, _proto, _canon, sockaddr in addresses:
            ip = ipaddress.ip_address(sockaddr[0])
            if not ip.is_global:
                return f"non-public address is not allowed: {ip}"
        return None

    async def _fetch_page(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = payload.get("url")
        if not isinstance(url, str) or not url.strip():
            return {"status": "error", "error": "url is required"}

        for _ in range(_MAX_REDIRECTS + 1):
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return {"status": "error", "error": "only absolute http(s) URLs are allowed"}

            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            blocked_reason = await self._check_public_host(parsed.hostname, port)
            if blocked_reason:
                return {"status": "error", "blocked": True, "error": blocked_reason}

            try:
                async with self._client() as client, client.stream("GET", url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            return {"status": "error", "error": "redirect had no location"}
                        url = urljoin(url, location)
                        continue

                    if response.status_code >= 400:
                        return {"status": "error", "error": f"HTTP {response.status_code}"}

                    content_type = (
                        response.headers.get("content-type", "").split(";")[0].strip().lower()
                    )
                    if content_type not in _ALLOWED_CONTENT_TYPES:
                        return {
                            "status": "error",
                            "error": f"unsupported content-type: {content_type or 'unknown'}",
                        }

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > _MAX_RESPONSE_BYTES:
                            break
                        chunks.append(chunk)
                    body = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
            except httpx.HTTPError as exc:
                return {"status": "error", "error": f"fetch failed: {exc}"}

            if content_type == "text/html":
                text, title = _html_to_text(body)
            else:
                text, title = body.strip(), parsed.hostname

            return {
                "url": url,
                "title": title or parsed.hostname,
                "publisher": parsed.hostname,
                "published_at": None,
                "content_type": content_type,
                "content": text[:_MAX_CONTENT_CHARS],
                "bytes_read": len(body.encode("utf-8")),
            }

        return {"status": "error", "error": "too many redirects"}

    async def _calculator(self, payload: dict[str, Any]) -> dict[str, Any]:
        expression = payload.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            return {"status": "error", "error": "expression is required"}

        try:
            value = _evaluate_arithmetic(expression)
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as exc:
            return {"status": "error", "error": f"invalid arithmetic expression: {exc}"}

        if not math.isfinite(value):
            return {"status": "error", "error": "expression must produce a finite number"}
        return {"value": value, "expression": expression}

    def _error(self, request: ToolRequest, message: str, started_at: Any) -> ToolResult:
        return ToolResult(
            request_id=request.request_id,
            attempt_id=request.attempt_id,
            tool=request.tool,
            status="error",
            error=message,
            started_at=started_at,
            completed_at=utc_now(),
        )


def _evaluate_arithmetic(expression: str) -> float:
    tree = ast.parse(expression, mode="eval")
    return float(_evaluate_node(tree.body))


def _evaluate_node(node: ast.AST) -> float | int:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if type(node.op) is ast.Pow and abs(float(right)) > 100:
            raise ValueError("exponent too large")
        return _BINARY_OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_node(node.operand))
    raise ValueError(f"unsupported expression node: {type(node).__name__}")


__all__ = ["ToolExecutor"]
