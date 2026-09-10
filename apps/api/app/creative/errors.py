class CreativeProviderError(Exception):
    """Base for every error a CreativeProvider implementation raises —
    the type a caller depending on CreativeProvider (not on any specific
    provider) should catch. Mirrors
    app.publishing.errors.WebsitePublisherError's role for
    WebsitePublisher and app.analysis.errors.BusinessAnalyzerError's for
    BusinessAnalyzer."""


class CreativeCapabilityNotSupportedError(CreativeProviderError):
    """This provider does not, and will not, support the requested
    CreativeGenerationType — checked via CreativeProvider.supports before
    a call is even attempted (app.creative.orchestrator does this), so
    seeing this error signals a caller bypassed that check rather than a
    normal, expected failure mode."""


class CreativeProviderRequestError(CreativeProviderError):
    """The underlying provider call itself failed — network error,
    authentication, rate limit, a provider-reported failure, or (for
    HiggsfieldCreativeProvider today, see app.creative.higgsfield.provider)
    the integration not yet being wired to a real, documented endpoint
    contract."""
