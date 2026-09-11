"""Thin wrapper over the Anthropic Messages API's structured-output path
— identical shape to app.analysis.claude.client.AnthropicStructuredOutputClient
(same "no tools, no logging of the request/response, injectable client
for tests" boundary), specialized to
app.creative.frontend_engine.manifest.GeneratedProjectManifest instead of
BusinessAnalysisOutput. Kept as its own small client (not a generic
parameterization of the analysis one) since the two output schemas, system
prompts, and error-handling needs are unrelated beyond sharing this shape.
"""

from collections.abc import Iterable
from typing import Protocol

import anthropic
import pydantic
from anthropic.types import MessageParam

from app.creative.errors import CreativeProviderRequestError
from app.creative.frontend_engine.manifest import GeneratedProjectManifest

DEFAULT_MAX_TOKENS = 16000


class FrontendEngineProviderError(CreativeProviderRequestError):
    """The Anthropic request itself failed, or returned no usable
    structured output — the generation attempt fails; never a fabricated
    manifest."""


class _ParsedResponseLike(Protocol):
    parsed_output: GeneratedProjectManifest | None
    stop_reason: str | None


class _MessagesLike(Protocol):
    def parse(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: Iterable[MessageParam],
        output_format: type[GeneratedProjectManifest],
    ) -> _ParsedResponseLike: ...


class _AnthropicClientLike(Protocol):
    @property
    def messages(self) -> _MessagesLike: ...


class AnthropicManifestClient:
    def __init__(self, client: anthropic.Anthropic | _AnthropicClientLike, *, model: str) -> None:
        self._client = client
        self._model = model

    def generate_manifest(self, *, system: str, user_content: str) -> GeneratedProjectManifest:
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=DEFAULT_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user_content}],
                output_format=GeneratedProjectManifest,
            )
        except pydantic.ValidationError as exc:
            raise FrontendEngineProviderError(
                "The frontend engine's response did not match the required manifest schema."
            ) from exc
        except anthropic.AnthropicError as exc:
            raise FrontendEngineProviderError(f"The LLM provider request failed: {exc}") from exc

        if response.parsed_output is None:
            raise FrontendEngineProviderError(
                f"The frontend engine returned no usable manifest (stop_reason={response.stop_reason!r})."
            )
        return response.parsed_output
