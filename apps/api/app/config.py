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

    # HiggsfieldCreativeProvider (app.creative.higgsfield.provider) — LEGACY,
    # P0-era scaffolding for the old CreativeLevel PREMIUM/CINEMATIC tier
    # (app.creative.orchestrator.select_provider), unrelated to and never
    # used by the real P2 Higgsfield Creative Director below. Every method
    # still raises HiggsfieldNotIntegratedError (see that module's own
    # docstring) — kept only because app.dependencies.get_optional_higgsfield_provider
    # is still wired into that older, separate generation path; do not
    # confuse this with higgsfield_api_key_id/_secret below, which is the
    # real, production P2 credential.
    higgsfield_api_key: str | None = None
    higgsfield_base_url: str | None = None

    # HiggsfieldCreativeDirector (app.creative.higgsfield.director, P2) —
    # PRODUCTION path: the official Higgsfield REST API
    # (app.creative.higgsfield.api_client.HiggsfieldApiClient), authenticated
    # with a server-side API key pair created in Higgsfield Cloud
    # (cloud.higgsfield.ai) — `Authorization: Key <id>:<secret>`. No
    # default on either half: a server without both configured still
    # starts up fine (see app.dependencies.get_optional_higgsfield_director),
    # and falls back to InternalCreativeDirector until they're set.
    # `higgsfield_api_key_name` is optional, non-secret operator metadata
    # (the key's display name in Higgsfield Cloud) — useful for capability
    # reporting/logging, never used for authentication itself.
    higgsfield_api_key_id: str | None = None
    higgsfield_api_key_secret: str | None = None
    higgsfield_api_key_name: str | None = None
    # The official REST API has no cost-estimate endpoint (confirmed
    # against the published OpenAPI spec — see docs/higgsfield-integration.md)
    # and no generation response ever reports actual credits spent, unlike
    # the CLI's own `generate cost`. This is therefore a deliberately
    # conservative, configurable *estimate* used only for
    # CreativeBudget.record_spend's own pre-flight enforcement — never
    # presented as a Higgsfield-confirmed figure.
    higgsfield_api_estimated_credits_per_call: float = 2.0
    higgsfield_api_base_url: str = "https://api.higgsfield.ai"
    higgsfield_api_timeout_seconds: float = 60.0

    # HiggsfieldCli/HiggsfieldCreativeDirector-over-CLI — retained ONLY for
    # local development and the manually-run real_provider test
    # (tests/test_higgsfield_real.py), never selected in production: this
    # integration uses the `higgsfield` CLI's own already-authenticated
    # local OAuth session (`higgsfield auth login`, external to this
    # codebase) rather than a server-held credential, which is why it's an
    # explicit, machine-local opt-in that defaults to disabled — an
    # unattended production deployment has no interactive session to hold
    # that OAuth token. See docs/higgsfield-integration.md.
    higgsfield_cli_enabled: bool = False
    higgsfield_cli_binary: str = "higgsfield"
    higgsfield_cli_timeout_seconds: float = 240.0

    # GoogleReviewProvider (app.reviews.provider) — no defaults, same
    # shape as every other optional provider credential above: reviews
    # import stays fully manual (already real and working) until a real
    # Google Places/Business Profile API credential is configured.
    google_reviews_api_key: str | None = None
    google_reviews_place_id: str | None = None

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

    # CloudflareR2StorageProvider (app.storage.r2, P2.1) — production
    # persistent storage: Railway's own local filesystem is ephemeral, so a
    # redeploy would silently destroy GenerativeWebsiteArtifact source
    # archives and Visual QA screenshots under LocalStorageProvider. No
    # default on any of these: a server without all four configured falls
    # back to LocalStorageProvider (see app.dependencies.get_storage_provider),
    # exactly like every other optional provider above — never a silent,
    # half-configured R2 attempt. `r2_public_base_url` is the bucket's own
    # public URL (an r2.dev subdomain or a custom domain) — StorageProvider
    # callers may receive either a root-relative path (LocalStorageProvider)
    # or this absolute URL from `url_path`; see that ABC's own docstring.
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket_name: str | None = None
    r2_public_base_url: str | None = None

    # InMemoryRateLimiter (app.security.rate_limit) budgets for the two
    # abuse-sensitive endpoints identified in the P0 security pass:
    # anonymous public lead submission and asset upload. Real defaults —
    # not credentials — safe to ship as-is; override per deployment.
    public_lead_rate_limit_per_minute: int = 10
    asset_upload_rate_limit_per_minute: int = 20
    # "Check now" (app.routers.website_health) makes real outbound HTTP/
    # DNS/TLS calls — cheap for a human clicking a button occasionally,
    # not something to leave uncapped.
    website_health_rate_limit_per_minute: int = 6
    # GET .../frontend-engineer-availability makes a real, minimal
    # Anthropic API call on demand (no free "ping" endpoint exists) — a
    # cheap, occasional operator action, not something a UI should ever
    # call unprompted, same "real outbound check, rate-limited" shape as
    # website_health_rate_limit_per_minute above.
    frontend_engineer_availability_rate_limit_per_minute: int = 6
    # GET .../generative-pipeline-capability (P2.1) makes one real,
    # non-billable Higgsfield status lookup on demand (see
    # app.creative.higgsfield.availability) — same "real outbound check,
    # rate-limited" shape as frontend_engineer_availability_rate_limit_per_minute
    # above, so it's never something a UI could hammer unprompted even
    # though the call itself never spends credits.
    generative_pipeline_capability_rate_limit_per_minute: int = 6
    # POST /public/businesses/{id}/events (app.routers.analytics, P1.7) —
    # anonymous, same abuse-sensitivity shape as public_lead above, but a
    # higher budget since a single real page view fires several distinct
    # events (page_view, several *_click events) in quick succession.
    public_analytics_rate_limit_per_minute: int = 60


settings = Settings()
