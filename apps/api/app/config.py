from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    service_name: str = "generate-web-ai-api"
    version: str = "0.1.0"

    # Postgres in every real deployment; sqlite is only the zero-config
    # local-dev/test default (see docs/architecture.md's decision log on
    # storage) — never assume sqlite-specific behavior outside tests.
    database_url: str = "sqlite:///./dev.db"

    # Fernet key backing app.security.encryption.CredentialCipher. No
    # default on purpose: a missing key must fail loudly at startup, not
    # silently fall back to something guessable. Unused until the API
    # exposes any Credential-writing endpoint (out of scope so far).
    credential_encryption_key: str | None = None

    # The Studio dashboard's dev origin — the only cross-origin caller
    # that exists yet (no public API surface, no third-party integration
    # calls this service).
    cors_origins: list[str] = ["http://localhost:5173"]

    # N8nAutomationEngine (app/automation/n8n) — no defaults for base
    # URL/API key: a missing value must fail loudly when the engine is
    # actually used, not silently point at nothing.
    n8n_base_url: str | None = None
    n8n_api_key: str | None = None

    # Where this API itself is reachable from an n8n workflow, for the
    # actions (lead.store, notification.send) that have no dedicated n8n
    # node and instead call back into our own backend.
    internal_api_base_url: str = "http://localhost:8000"

    # AnthropicBusinessAnalyzer (app.analysis.claude) — no default: a
    # missing key must fail loudly when the analyzer is actually used,
    # not silently point at nothing. Never logged, never accepted from a
    # request — this analyzer receives no credentials at all, its own or
    # anyone else's.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"

    # Shared secret n8n sends back to /internal/leads and
    # /internal/notifications (see app.dependencies.verify_internal_automation_token)
    # to prove the caller is our own n8n workflow, not the public
    # internet — no default, so a missing value fails loudly instead of
    # leaving these endpoints silently open.
    internal_automation_token: str | None = None
    # The n8n-side credential *reference* (an "HTTP Header Auth"
    # credential n8n already has configured, carrying the same token
    # value) that the translator attaches to lead.store/notification.send
    # nodes — never the raw token itself.
    n8n_internal_automation_credential_id: str | None = None

    # CloudflarePagesPublisher (app.publishing.cloudflare) — no
    # defaults, same shape as the n8n settings above: a missing value
    # must fail loudly when publishing is actually attempted, not
    # silently point at nothing. No workers.dev/pages.dev subdomain
    # setting needed here — a Pages project's live URL
    # (https://{project}.pages.dev) needs no account-level config, and
    # custom domains are out of scope for this phase.
    cloudflare_account_id: str | None = None
    cloudflare_api_token: str | None = None

    # SmtpNotificationSender (app.notifications.smtp) — the transport
    # behind internal-notification email delivery. No defaults for
    # host/from address: a server without them still starts up fine,
    # delivery is just skipped as "not configured yet" (see
    # app.dependencies.get_optional_notification_sender) rather than
    # failing loudly, since not every business needs email notifications
    # configured from day one. `smtp_password` is never logged.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_address: str | None = None

    # ResendNotificationSender (app.notifications.resend) — the
    # cloud-safe HTTP transport preferred over SMTP above whenever it's
    # configured (see app.dependencies.get_optional_notification_sender):
    # most serverless/edge deployment targets either block outbound SMTP
    # or make it unreliable, while an HTTPS API call is not blocked.
    # Same "no defaults, delivery is just skipped until configured" shape
    # as the SMTP settings — `resend_api_key` is never logged.
    resend_api_key: str | None = None
    resend_from_address: str | None = None

    # HiggsfieldCreativeProvider (app.creative.higgsfield) — no defaults,
    # same shape as every other provider credential above: a server
    # without them still starts up fine; premium creative generation only
    # fails, loudly and with a clean 503, the first time it's actually
    # attempted (see app.dependencies.get_higgsfield_provider). No real
    # Higgsfield integration exists yet regardless of these being set —
    # see app.creative.higgsfield.provider's own docstring.
    higgsfield_api_key: str | None = None
    higgsfield_base_url: str | None = None

    # LocalStorageProvider (app.storage.local) — the dev-only asset
    # storage backend (Phase 3 of the Creative Orchestrator work). Unlike
    # every credential above, this has a real default: local storage
    # needs no account/credentials of any kind, and must work out of the
    # box the same way sqlite:///./dev.db does for the database.
    # Relative to wherever the API process runs (apps/api in dev).
    local_storage_dir: str = "var/uploads"
    # Max upload size for a single business asset — a plain safety limit
    # (Phase 3: "reasonable size limits"), not tied to any provider's own
    # quota.
    max_upload_size_bytes: int = 10 * 1024 * 1024


settings = Settings()
