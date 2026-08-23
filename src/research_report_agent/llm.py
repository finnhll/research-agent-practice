"""Async LLM client: structured output validated against a Pydantic schema.

Same design decision as the sibling ``sentinel`` project's ``moderator.ts``: the model
produces raw structured judgments; validation and the repair-retry policy live in code,
not in a prompt hope. Every agent in this package calls ``complete_structured`` and
trusts only the validated Pydantic object it returns.

Two backends share that interface, selected by ``ModelConfig.provider``:

- ``_OpenAICompatibleBackend`` — OpenAI and DeepSeek (and any other OpenAI-compatible
  gateway reached by picking "openai" with a custom ``base_url``). Uses JSON mode
  (``response_format: json_object``) plus ``model_validate_json`` in code.
- ``_AnthropicBackend`` — Claude's Messages API is a different wire format entirely
  (no ``response_format``, different auth). Uses the SDK's native
  ``messages.parse(output_format=schema)``, which validates against the schema
  server-side and hands back an already-parsed instance.
"""

from __future__ import annotations

from typing import TypeVar

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from research_report_agent.config import ModelConfig

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# Non-streaming ceiling for Claude's structured-output calls. Generous because
# thinking is on by default for current-generation models and counts against it.
_ANTHROPIC_MAX_TOKENS = 16000

# Per-HTTP-request timeout and SDK-level retry cap for both backends. Measured live
# against DeepSeek: a single slow/erroring provider response can otherwise let the
# SDK's own retry-with-backoff run well past the orchestrator's asyncio.wait_for
# attempt budget (RunBudget.attempt_timeout_seconds) before that outer cancellation
# is ever delivered. Bounding each individual request here is the actual fix; the
# outer timeout alone does not reliably bound total latency.
_REQUEST_TIMEOUT_SECONDS = 60.0
_SDK_MAX_RETRIES = 1


class LLMError(RuntimeError):
    """Raised when the model cannot produce schema-valid output after repairs."""


class _OpenAICompatibleBackend:
    """OpenAI, DeepSeek, and any other OpenAI-compatible endpoint."""

    def __init__(self, config: ModelConfig) -> None:
        self._model = config.model
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            max_retries=_SDK_MAX_RETRIES,
        )

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
        max_repairs: int,
    ) -> SchemaT:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_error: Exception | None = None

        for attempt in range(max_repairs + 1):
            response = await self._client.chat.completions.create(
                model=self._model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=messages,  # type: ignore[arg-type]
            )
            content = response.choices[0].message.content or ""
            try:
                return schema.model_validate_json(content)
            except ValidationError as exc:
                last_error = exc
                feedback = f"That response failed schema validation:\n{exc}"
            except ValueError as exc:
                last_error = exc
                feedback = f"That response was not valid JSON: {exc}"

            if attempt >= max_repairs:
                break
            messages.append({"role": "assistant", "content": content})
            repair_prompt = (
                f"{feedback}\n\nReturn corrected JSON only, matching the required shape."
            )
            messages.append({"role": "user", "content": repair_prompt})

        raise LLMError(
            f"Model failed to produce valid {schema.__name__} after repairs: {last_error}"
        )

    async def list_model_ids(self) -> list[str]:
        response = await self._client.models.list()
        return [item.id for item in response.data]


class _AnthropicBackend:
    """Claude via the native Messages API structured-output path."""

    def __init__(self, config: ModelConfig) -> None:
        self._model = config.model
        self._client = AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            max_retries=_SDK_MAX_RETRIES,
        )

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
        max_repairs: int,
    ) -> SchemaT:
        # No `temperature` here: on current-generation models (Opus 5, Sonnet 5,
        # Opus 4.7/4.8) sampling params are rejected outright (HTTP 400) because
        # thinking is adaptive by default. Determinism instead comes from the
        # schema-constrained output_format, not from temperature.
        last_error: Exception | None = None
        note = ""

        for _attempt in range(max_repairs + 1):
            try:
                response = await self._client.messages.parse(
                    model=self._model,
                    max_tokens=_ANTHROPIC_MAX_TOKENS,
                    system=system,
                    messages=[{"role": "user", "content": user + note}],
                    output_format=schema,
                )
                if response.parsed_output is None:
                    raise LLMError(
                        f"Claude returned no parsed output (stop_reason={response.stop_reason})"
                    )
                return response.parsed_output
            except Exception as exc:  # SDK/validation/refusal all feed the repair loop
                last_error = exc
                note = (
                    f"\n\nNote: a previous attempt failed validation: {exc}. "
                    "Return output that strictly matches the required schema."
                )

        raise LLMError(
            f"Model failed to produce valid {schema.__name__} after repairs: {last_error}"
        )

    async def list_model_ids(self) -> list[str]:
        return [item.id async for item in self._client.models.list()]


class LLMClient:
    """Structured-output client bound to one provider/model, with schema repair."""

    def __init__(self, config: ModelConfig) -> None:
        if not config.api_key:
            raise LLMError("No model API key configured")
        self._backend: _OpenAICompatibleBackend | _AnthropicBackend
        if config.provider == "anthropic":
            self._backend = _AnthropicBackend(config)
        else:
            self._backend = _OpenAICompatibleBackend(config)

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[SchemaT],
        max_repairs: int = 1,
    ) -> SchemaT:
        """Call the model and return its reply validated against ``schema``.

        On invalid output, retries up to ``max_repairs`` times with the error fed
        back to the model, matching the repair policy documented in
        ``docs/spec/design.md`` (planner/worker/report schema repair).
        """

        return await self._backend.complete_structured(
            system=system,
            user=user,
            schema=schema,
            max_repairs=max_repairs,
        )

    async def list_model_ids(self) -> list[str]:
        """Used only by the Settings panel's "Test connection" action."""

        return await self._backend.list_model_ids()


__all__ = ["LLMClient", "LLMError"]
