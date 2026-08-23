from __future__ import annotations

import httpx
import pytest

from research_report_agent.runtime_contracts import ToolRequest
from research_report_agent.tools import ToolExecutor

_SEARCH_HTML = """
<div class="results">
  <div class="result">
    <h2 class="result__title">
      <a class="result__a"
         href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage1&rut=abc"
         >Example Page 1</a>
    </h2>
    <a class="result__snippet" href="#">Snippet about page one.</a>
  </div>
  <div class="result">
    <h2 class="result__title">
      <a class="result__a" href="https://example.com/page2">Example Page 2</a>
    </h2>
    <a class="result__snippet" href="#">Snippet about page two.</a>
  </div>
</div>
"""

_PAGE_HTML = (
    "<html><head><title>Test Page</title></head>"
    "<body><script>evil()</script><p>Real content here.</p></body></html>"
)


def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    html_headers = {"content-type": "text/html; charset=utf-8"}
    if "html.duckduckgo.com" in url:
        return httpx.Response(200, text=_SEARCH_HTML)
    if url == "http://1.1.1.1/redirect":
        return httpx.Response(302, headers={"location": "http://1.1.1.1/final"})
    if url == "http://1.1.1.1/private-redirect":
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
    if url in {"http://1.1.1.1/page", "http://1.1.1.1/final"}:
        return httpx.Response(200, text=_PAGE_HTML, headers=html_headers)
    if url == "http://1.1.1.1/not-found":
        return httpx.Response(404)
    return httpx.Response(500)


@pytest.fixture
def executor() -> ToolExecutor:
    return ToolExecutor(transport=httpx.MockTransport(_handler))


def request(executor: ToolExecutor, tool: str, payload: dict[str, object]) -> ToolRequest:
    return ToolRequest(
        request_id=f"tool_req_{executor.call_count + 1}",
        attempt_id="task_001_attempt_001",
        tool=tool,
        input=payload,
    )


async def test_web_search_parses_and_unwraps_results(executor: ToolExecutor) -> None:
    result = await executor.execute(request(executor, "web_search", {"query": "example"}))

    assert result.status.value == "success"
    urls = [item["url"] for item in result.output["results"]]
    assert "https://example.com/page1" in urls
    assert "https://example.com/page2" in urls


async def test_web_search_requires_query(executor: ToolExecutor) -> None:
    result = await executor.execute(request(executor, "web_search", {}))

    assert result.status.value == "error"
    assert result.error == "query is required"


async def test_fetch_page_rejects_private_network(executor: ToolExecutor) -> None:
    result = await executor.execute(
        request(executor, "fetch_page", {"url": "http://127.0.0.1:8000/admin"})
    )

    assert result.status.value == "blocked"
    assert "non-public address" in result.error


async def test_fetch_page_strips_scripts_and_returns_text(executor: ToolExecutor) -> None:
    result = await executor.execute(request(executor, "fetch_page", {"url": "http://1.1.1.1/page"}))

    assert result.status.value == "success"
    assert result.output["title"] == "Test Page"
    assert "evil()" not in result.output["content"]
    assert "Real content here." in result.output["content"]


async def test_fetch_page_follows_and_revalidates_redirects(executor: ToolExecutor) -> None:
    result = await executor.execute(
        request(executor, "fetch_page", {"url": "http://1.1.1.1/redirect"})
    )

    assert result.status.value == "success"
    assert result.output["url"] == "http://1.1.1.1/final"


async def test_fetch_page_blocks_redirect_to_private_network(executor: ToolExecutor) -> None:
    result = await executor.execute(
        request(executor, "fetch_page", {"url": "http://1.1.1.1/private-redirect"})
    )

    assert result.status.value == "blocked"


async def test_fetch_page_reports_http_errors(executor: ToolExecutor) -> None:
    result = await executor.execute(
        request(executor, "fetch_page", {"url": "http://1.1.1.1/not-found"})
    )

    assert result.status.value == "error"
    assert "404" in result.error


async def test_calculator_evaluates_without_exec(executor: ToolExecutor) -> None:
    result = await executor.execute(request(executor, "calculator", {"expression": "(2 + 3) * 4"}))

    assert result.status.value == "success"
    assert result.output["value"] == 20


@pytest.mark.parametrize("expression", ["2 +", "import os", "__import__('os')"])
async def test_calculator_rejects_invalid_expression(
    executor: ToolExecutor,
    expression: str,
) -> None:
    result = await executor.execute(request(executor, "calculator", {"expression": expression}))

    assert result.status.value == "error"


async def test_unknown_tool_is_rejected(executor: ToolExecutor) -> None:
    result = await executor.execute(request(executor, "shell", {"command": "ls"}))

    assert result.status.value == "error"
