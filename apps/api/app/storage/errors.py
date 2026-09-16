class StorageProviderError(Exception):
    """The underlying StorageProvider call itself failed — network error,
    bad credentials, a misconfigured bucket/account, or a provider-side
    fault. Mirrors app.creative.errors.CreativeProviderError's role for
    CreativeProvider: a caller depending on StorageProvider (not on any
    specific implementation) should catch this, never a provider-specific
    exception type (e.g. botocore.exceptions.ClientError), so a router can
    map it to one structured AppError response regardless of which
    provider is active."""
