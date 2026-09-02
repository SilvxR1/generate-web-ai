"""Thin wrapper over the Anthropic Messages API's structured-output path
(client.messages.parse) — the only call this module makes. `tools` is
never passed: nothing here can execute an action, only return data
(the "no tools/function execution" boundary). No retry logic here (the
SDK already retries connection errors, 429, and 5xx); no logging of the
request (it embeds the untrusted briefing) or of the API key.

The constructor also accepts `_AnthropicClientLike`, a structural
(Protocol) stand-in for `anthropic.Anthropic`, so tests can inject a fake
object shaped like `{"messages": {"parse": ...}}` without needing a real
API key, an HTTP mock, or network access — mirroring how
app.automation.n8n.client.N8nClient accepts an injected http_client.
"""

from collections.abc import Iterable
from typing import Protocol

import anthropic
import pydantic
from anthropic.types import MessageParam

from app.analysis.errors import AnalyzerProviderError, InvalidAnalysisOutputError
from app.analysis.schema import BusinessAnalysisOutput

DEFAULT_MAX_TOKENS = 4096


class _ParsedResponseLike(Protocol):
    parsed_output: BusinessAnalysisOutput | None
    stop_reason: str | None


class _MessagesLike(Protocol):
    def parse(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: Iterable[MessageParam],
        output_format: type[BusinessAnalysisOutput],
    ) -> _ParsedResponseLike: ...


class _AnthropicClientLike(Protocol):
    @property
    def messages(self) -> _MessagesLike: ...


class AnthropicStructuredOutputClient:
    # `anthropic.Anthropic` is accepted directly (the real, production
    # path) alongside the structural `_AnthropicClientLike` (what tests
    # inject) rather than typed as the Protocol alone: `Messages.parse`
    # is a generic SDK method, and mypy's Protocol conformance check
    # doesn't specialize its TypeVar against our concrete
    # BusinessAnalysisOutput — a known limitation, not a real type
    # mismatch (see the call site below, which type-checks fine).
    def __init__(self, client: anthropic.Anthropic | _AnthropicClientLike, *, model: str) -> None:
        self._client = client
        self._model = model

    def analyze(self, *, system: str, user_content: str) -> tuple[BusinessAnalysisOutput | None, str | None]:
        """Returns (parsed_output, stop_reason). `parsed_output` is None
        when the model produced no usable structured output (e.g. a
        safety refusal) — the caller (AnthropicBusinessAnalyzer) decides
        what that means, this layer only reports it."""
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=DEFAULT_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user_content}],
                output_format=BusinessAnalysisOutput,
            )
        except pydantic.ValidationError as exc:
            raise InvalidAnalysisOutputError(
                "The analyzer's response did not match the required structured-output schema."
            ) from exc
        except anthropic.AnthropicError as exc:
            raise AnalyzerProviderError(f"The LLM provider request failed: {exc}") from exc

        return response.parsed_output, response.stop_reason
