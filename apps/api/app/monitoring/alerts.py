"""send_operator_alert — the one operator-facing alert transport this
codebase has (A6.1). Deliberately provider-neutral: any endpoint that
accepts a JSON POST body works. The first real production destination
is expected to be a Slack incoming webhook, so the payload's `text`
field is formatted to render sensibly there, but nothing else here is
Slack-specific — no Block Kit, no channel/username fields, no import of
a Slack SDK. A different transport just needs a URL that accepts
{"text": "..."}.

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


class AlertSeverity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"


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
    """
    if not settings.alert_webhook_url:
        return

    lines = [f"[{severity.value.upper()}] {operation}: {summary}"]
    if business_id is not None:
        lines.append(f"business_id: {business_id}")
    if tenant_id is not None:
        lines.append(f"tenant_id: {tenant_id}")
    if lead_id is not None:
        lines.append(f"lead_id: {lead_id}")
    lines.append(f"environment: {settings.environment} · {datetime.now(UTC).isoformat()}")

    try:
        response = httpx.post(
            settings.alert_webhook_url, json={"text": "\n".join(lines)}, timeout=_ALERT_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # httpx.HTTPStatusError's own str() embeds the request URL —
        # never pass it to the logger directly. The status code alone
        # is enough to diagnose a failing webhook.
        logger.error(
            "Operator alert delivery failed (operation=%s, severity=%s): webhook returned HTTP %s",
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
            "Operator alert delivery failed (operation=%s, severity=%s): %s",
            operation,
            severity.value,
            type(exc).__name__,
        )
