"""send_operator_alert — the one operator-facing alert transport this
codebase has (A6.1/A6.3). Deliberately provider-neutral: the alert text
itself is built once, then wrapped into whichever JSON shape the
configured ALERT_WEBHOOK_PROVIDER needs — "discord" ({"content": ...})
or "slack" ({"text": ...}). No Block Kit, no embeds, no bot/SDK
integration for either — a plain webhook POST is enough for the pilot.
The provider is always an explicit setting (ALERT_WEBHOOK_PROVIDER),
never guessed by inspecting or parsing the URL's hostname — a config
mistake should fail loudly (a logged warning, no alert sent) rather
than silently pick a payload shape that might be wrong.

Deliberately best-effort and NEVER raises. send_operator_alert() is
always called from inside a caller that is already handling a real,
different failure (a publish that failed, an email that didn't send) —
a broken, unconfigured, or slow alert webhook must never become a
SECOND failure that replaces or masks the first one, and must never
make an otherwise-successful operation (e.g. a lead that persisted
fine) fail just because alerting about something else went wrong. A
bare `except Exception` below is deliberate for exactly this reason:
the contract is "never propagates," not "never propagates for the
exception types we thought of."

Not wired to itself: a failure delivering an alert is logged, never
re-alerted (that would either loop forever against a webhook that's the
actual thing that's down, or silently swallow the one signal an
operator needed).

No history/persistence: alerts are fire-and-forget HTTP calls, never
written to the database (A6.1's explicit "no database persistence
required").
"""

import logging
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Short and explicit: an operator alert must never become the reason a
# request handler runs noticeably slower, let alone times out, just
# because the webhook destination is unresponsive.
_ALERT_TIMEOUT_SECONDS = 5.0

# Discord's own hard limit on a webhook message's `content` field. Slack
# incoming webhooks tolerate far more (~40,000 chars), but capping every
# provider at the smaller, stricter bound keeps this one code path
# simple and guarantees Discord never rejects a message for length —
# "prefer safely truncating... rather than allowing Discord to reject
# an oversized message."
_MAX_MESSAGE_LENGTH = 2000
_TRUNCATION_SUFFIX = "… (truncated)"

_PAYLOAD_KEY_BY_PROVIDER = {"discord": "content", "slack": "text"}


class AlertSeverity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"


def _build_message(
    severity: AlertSeverity,
    *,
    operation: str,
    summary: str,
    business_id: UUID | None,
    tenant_id: UUID | None,
    lead_id: UUID | None,
) -> str:
    lines = [f"[{severity.value.upper()}] {operation}: {summary}"]
    if business_id is not None:
        lines.append(f"business_id: {business_id}")
    if tenant_id is not None:
        lines.append(f"tenant_id: {tenant_id}")
    if lead_id is not None:
        lines.append(f"lead_id: {lead_id}")
    lines.append(f"environment: {settings.environment} · {datetime.now(UTC).isoformat()}")

    message = "\n".join(lines)
    if len(message) > _MAX_MESSAGE_LENGTH:
        message = message[: _MAX_MESSAGE_LENGTH - len(_TRUNCATION_SUFFIX)] + _TRUNCATION_SUFFIX
    return message


def send_operator_alert(
    severity: AlertSeverity,
    *,
    operation: str,
    summary: str,
    business_id: UUID | None = None,
    tenant_id: UUID | None = None,
    lead_id: UUID | None = None,
) -> None:
    """Best-effort, fire-and-forget. A silent no-op when
    ALERT_WEBHOOK_URL isn't configured — the same "missing optional
    provider degrades silently" shape as
    app.dependencies.get_optional_n8n_client, not a required credential
    like credential_encryption_key. `summary` must already be a short,
    sanitized message (an exception's `str(exc)`, never a raw provider
    response body, template/email content, or anything containing a
    secret) — this function does no further redaction of its own,
    exactly like WebsiteHealthCheck.error_summary's own convention.

    A URL configured with a missing or unsupported ALERT_WEBHOOK_PROVIDER
    is also a no-op — never a guess at what the URL might accept — logged
    once as a configuration warning (never the URL itself) so a
    misconfigured pilot deployment doesn't fail silently forever.
    """
    if not settings.alert_webhook_url:
        return

    provider = (settings.alert_webhook_provider or "").strip().lower()
    payload_key = _PAYLOAD_KEY_BY_PROVIDER.get(provider)
    if payload_key is None:
        logger.warning(
            "ALERT_WEBHOOK_URL is configured but ALERT_WEBHOOK_PROVIDER is missing or unsupported "
            "(got %r; supported: %s) — no alert sent.",
            settings.alert_webhook_provider,
            ", ".join(sorted(_PAYLOAD_KEY_BY_PROVIDER)),
        )
        return

    message = _build_message(
        severity, operation=operation, summary=summary, business_id=business_id, tenant_id=tenant_id, lead_id=lead_id
    )

    try:
        response = httpx.post(settings.alert_webhook_url, json={payload_key: message}, timeout=_ALERT_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # httpx.HTTPStatusError's own str() embeds the request URL —
        # never pass it to the logger directly. The status code alone
        # is enough to diagnose a failing webhook.
        logger.error(
            "Operator alert delivery failed (provider=%s, operation=%s, severity=%s): webhook returned HTTP %s",
            provider,
            operation,
            severity.value,
            exc.response.status_code,
        )
    except Exception as exc:  # noqa: BLE001 — see module docstring: this must never propagate.
        # Every other failure mode (timeout, connection error, ...) —
        # the exception class name is enough to diagnose it; never
        # str(exc), which for some httpx exceptions can also embed the
        # URL (and, by extension, the webhook itself).
        logger.error(
            "Operator alert delivery failed (provider=%s, operation=%s, severity=%s): %s",
            provider,
            operation,
            severity.value,
            type(exc).__name__,
        )
