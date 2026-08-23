from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict, Field

from research_report_agent.config import ModelConfig
from research_report_agent.llm import (
    LLMClient,
    LLMError,
    _AnthropicBackend,
    _OpenAICompatibleBackend,
)


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int = Field(gt=0)


class _FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.calls = 0

    async def create(self, **_kwargs: object) -> SimpleNamespace:
        self.calls += 1
        content = self._contents.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _openai_client(contents: list[str]) -> tuple[LLMClient, _FakeCompletions]:
    client = LLMClient(ModelConfig(provider="openai", model="test-model", api_key="test-key"))
    completions = _FakeCompletions(contents)
    client._backend._client = SimpleNamespace(  # type: ignore[attr-defined]
        chat=SimpleNamespace(completions=completions)
    )
    return client, completions


class _FakeAnthropicMessages:
    """Scripted replies for ``messages.parse`` — either a value or an exception."""

    def __init__(self, replies: list[object]) -> None:
        self._replies = list(replies)
        self.calls: list[dict[str, object]] = []

    async def parse(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _anthropic_client(replies: list[object]) -> tuple[LLMClient, _FakeAnthropicMessages]:
    client = LLMClient(ModelConfig(provider="anthropic", model="claude-opus-5", api_key="test-key"))
    messages = _FakeAnthropicMessages(replies)
    client._backend._client = SimpleNamespace(messages=messages)  # type: ignore[attr-defined]
    return client, messages


def test_missing_api_key_raises_llm_error() -> None:
    with pytest.raises(LLMError):
        LLMClient(ModelConfig(model="test-model", api_key=None))


def test_default_provider_uses_openai_compatible_backend() -> None:
    client = LLMClient(ModelConfig(provider="openai", model="m", api_key="k"))
    assert isinstance(client._backend, _OpenAICompatibleBackend)


def test_deepseek_provider_uses_openai_compatible_backend() -> None:
    client = LLMClient(
        ModelConfig(
            provider="deepseek",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            api_key="k",
        )
    )
    assert isinstance(client._backend, _OpenAICompatibleBackend)


def test_anthropic_provider_uses_anthropic_backend() -> None:
    client = LLMClient(ModelConfig(provider="anthropic", model="claude-opus-5", api_key="k"))
    assert isinstance(client._backend, _AnthropicBackend)


async def test_complete_structured_returns_valid_response_first_try() -> None:
    client, completions = _openai_client([json.dumps({"value": 5})])

    result = await client.complete_structured(system="s", user="u", schema=_Schema)

    assert result.value == 5
    assert completions.calls == 1


async def test_complete_structured_repairs_invalid_json() -> None:
    client, completions = _openai_client(["not json at all", json.dumps({"value": 7})])

    result = await client.complete_structured(system="s", user="u", schema=_Schema)

    assert result.value == 7
    assert completions.calls == 2


async def test_complete_structured_repairs_schema_violation() -> None:
    client, completions = _openai_client([json.dumps({"value": -1}), json.dumps({"value": 3})])

    result = await client.complete_structured(system="s", user="u", schema=_Schema)

    assert result.value == 3
    assert completions.calls == 2


async def test_complete_structured_raises_after_exhausting_repairs() -> None:
    client, completions = _openai_client([json.dumps({"value": -1}), json.dumps({"value": -2})])

    with pytest.raises(LLMError):
        await client.complete_structured(system="s", user="u", schema=_Schema, max_repairs=1)

    assert completions.calls == 2


async def test_anthropic_backend_returns_parsed_output_first_try() -> None:
    parsed = _Schema(value=9)
    client, messages = _anthropic_client(
        [SimpleNamespace(parsed_output=parsed, stop_reason="end_turn")]
    )

    result = await client.complete_structured(system="s", user="u", schema=_Schema)

    assert result is parsed
    assert len(messages.calls) == 1
    assert messages.calls[0]["system"] == "s"
    assert "temperature" not in messages.calls[0]


async def test_anthropic_backend_repairs_after_no_parsed_output() -> None:
    parsed = _Schema(value=2)
    client, messages = _anthropic_client(
        [
            SimpleNamespace(parsed_output=None, stop_reason="refusal"),
            SimpleNamespace(parsed_output=parsed, stop_reason="end_turn"),
        ]
    )

    result = await client.complete_structured(system="s", user="u", schema=_Schema)

    assert result is parsed
    assert len(messages.calls) == 2
    assert "previous attempt failed" in messages.calls[1]["messages"][0]["content"]


async def test_anthropic_backend_raises_after_exhausting_repairs() -> None:
    client, messages = _anthropic_client(
        [
            SimpleNamespace(parsed_output=None, stop_reason="refusal"),
            SimpleNamespace(parsed_output=None, stop_reason="refusal"),
        ]
    )

    with pytest.raises(LLMError):
        await client.complete_structured(system="s", user="u", schema=_Schema, max_repairs=1)

    assert len(messages.calls) == 2
