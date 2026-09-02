class BusinessAnalyzerError(Exception):
    """Base for every error a BusinessAnalyzer implementation raises — the
    type a caller depending on BusinessAnalyzer (not on any specific
    provider) should catch."""


class AnalyzerProviderError(BusinessAnalyzerError):
    """The underlying LLM provider request itself failed — network error,
    authentication, rate limit, 5xx. Nothing about the briefing or the
    (would-be) analysis is implicated."""


class InvalidAnalysisOutputError(BusinessAnalyzerError):
    """The provider's response didn't satisfy the structured-output
    contract (malformed JSON, a refusal, no output at all), or the
    assembled proposal failed BusinessConfig's own validation. Raised
    instead of ever returning a guessed-at or partially-trusted
    BusinessConfig."""
