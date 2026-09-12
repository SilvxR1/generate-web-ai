"""Thin wrapper over the Anthropic Messages API's structured-output path
— identical shape to app.analysis.claude.client.AnthropicStructuredOutputClient
(same "no tools, no logging of the request/response, injectable client
for tests" boundary), specialized to
app.creative.frontend_engine.manifest.GeneratedProjectManifest instead of
BusinessAnalysisOutput. Kept as its own small client (not a generic
parameterization of the analysis one) since the two output schemas, system
prompts, and error-handling needs are unrelated beyond sharing this shape.
"""

import logging
import time
from collections.abc import Iterable
from typing import Protocol

import anthropic
import pydantic
from anthropic.types import MessageParam

from app.creative.errors import CreativeProviderRequestError
from app.creative.frontend_engine.manifest import GeneratedProjectManifest

logger = logging.getLogger(__name__)

# A real multi-file manifest (home page + legal/consent pages + CSS) plus
# claude-opus-5's on-by-default thinking can exceed 16000 tokens and get cut
# off mid-JSON (pydantic.ValidationError: "EOF while parsing a string") —
# confirmed against the live API via tests/test_frontend_engine_real.py, not
# a guess. 32000 gives headroom for both without requiring streaming.
DEFAULT_MAX_TOKENS = 32000
# Bounds the live manifest-generation call so a stalled/slow provider surfaces
# as a clear timeout failure (FrontendEngineProviderError) instead of riding
# the SDK's own 10-minute default in silence — see tests/test_frontend_engine_real.py.
DEFAULT_TIMEOUT_SECONDS = 450.0


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

    def with_options(self, *, timeout: float | None = None) -> "_AnthropicClientLike": ...


class AnthropicManifestClient:
    def __init__(self, client: anthropic.Anthropic | _AnthropicClientLike, *, model: str) -> None:
        self._client = client
        self._model = model

    def generate_manifest(self, *, system: str, user_content: str) -> GeneratedProjectManifest:
        logger.info("frontend_engine anthropic request started (model=%s)", self._model)
        started = time.monotonic()
        try:
            # Request timeout is set via with_options(...) — the SDK's own
            # supported per-call override mechanism — rather than passed
            # directly to parse(), so the client's own type (Anthropic |
            # _AnthropicClientLike) stays exactly what messages.parse's real
            # signature expects; see this file's own _AnthropicClientLike.
            response = self._client.with_options(timeout=DEFAULT_TIMEOUT_SECONDS).messages.parse(
                model=self._model,
                max_tokens=DEFAULT_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user_content}],
                output_format=GeneratedProjectManifest,
            )
        except pydantic.ValidationError as exc:
            logger.warning("frontend_engine anthropic response failed schema validation")
            raise FrontendEngineProviderError(
                "The frontend engine's response did not match the required manifest schema."
            ) from exc
        except anthropic.AnthropicError as exc:
            duration_ms = round((time.monotonic() - started) * 1000, 1)
            logger.warning(
                "frontend_engine anthropic request failed after %sms (%s)", duration_ms, type(exc).__name__
            )
            raise FrontendEngineProviderError(f"The LLM provider request failed: {exc}") from exc

        duration_ms = round((time.monotonic() - started) * 1000, 1)
        logger.info(
            "frontend_engine anthropic response received in %sms (stop_reason=%s)",
            duration_ms,
            response.stop_reason,
        )

        if response.parsed_output is None:
            raise FrontendEngineProviderError(
                f"The frontend engine returned no usable manifest (stop_reason={response.stop_reason!r})."
            )
        logger.info("frontend_engine generated manifest parsed (files=%d)", len(response.parsed_output.files))
        return response.parsed_output
