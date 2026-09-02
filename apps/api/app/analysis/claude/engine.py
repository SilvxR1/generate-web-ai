"""AnthropicBusinessAnalyzer — the first, replaceable BusinessAnalyzer
implementation. Nothing outside app.analysis.claude should need to
know Claude/Anthropic is involved; callers depend on BusinessAnalyzer.
"""

import anthropic

from app.analysis.analyzer import BusinessAnalysisResult, BusinessAnalyzer
from app.analysis.assembly import assemble_result
from app.analysis.claude.client import AnthropicStructuredOutputClient
from app.analysis.claude.prompts import SYSTEM_PROMPT, build_user_message
from app.analysis.errors import InvalidAnalysisOutputError
from app.config import Settings

DEFAULT_MODEL = "claude-opus-5"


class AnthropicBusinessAnalyzer(BusinessAnalyzer):
    def __init__(self, client: AnthropicStructuredOutputClient) -> None:
        self._client = client

    def analyze(self, briefing: str) -> BusinessAnalysisResult:
        parsed_output, stop_reason = self._client.analyze(
            system=SYSTEM_PROMPT, user_content=build_user_message(briefing)
        )
        if parsed_output is None:
            raise InvalidAnalysisOutputError(
                f"The analyzer returned no structured output (stop_reason={stop_reason!r})."
            )
        return assemble_result(parsed_output)


def business_analyzer_from_settings(settings: Settings) -> AnthropicBusinessAnalyzer:
    """No default for `anthropic_api_key` (app.config.Settings) — a
    missing key must fail loudly when the analyzer is actually used, not
    silently point at nothing. Raises anthropic's own error (a
    `ValueError`, per the SDK's client constructor) rather than a
    friendlier app-level one; app.dependencies.get_business_analyzer is
    the layer that turns "not configured" into a clean 503 for callers.
    """
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return AnthropicBusinessAnalyzer(AnthropicStructuredOutputClient(client, model=settings.anthropic_model))
