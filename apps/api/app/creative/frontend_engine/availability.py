"""check_frontend_engineer_availability — honest, real-verified
provider-availability for the AI Frontend Engineer (P2 continuation Part
1). Mirrors GET .../creative-providers' "never a hardcoded placeholder"
discipline (app.routers.creative.list_creative_provider_availability),
but goes one step further: Anthropic has no free "ping" endpoint, so
"configured" alone can't distinguish a present-but-invalid key from a
working one. Rather than silently reporting "configured" as if it meant
"working" (dishonest) or making a real, cost-incurring call on every
Studio page load (wasteful), this is a real, minimal, on-demand check —
the same "manual, rate-limited real check" shape
app.routers.website_health's "Check now" button already uses for a
different external dependency.
"""

import anthropic

from app.config import Settings


def check_frontend_engineer_availability(settings: Settings) -> tuple[bool, str | None]:
    """Returns (available, unavailable_reason). Never raises — every
    failure mode (no key configured, invalid key, network error) is
    reported as `(False, <reason>)`; the key itself is never included in
    the reason or logged anywhere in this call path."""
    if not settings.anthropic_api_key:
        return False, "ANTHROPIC_API_KEY is not configured on this server."

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=1, messages=[{"role": "user", "content": "ping"}]
        )
    except anthropic.AuthenticationError:
        return False, "ANTHROPIC_API_KEY is configured but was rejected by Anthropic (invalid or revoked)."
    except anthropic.AnthropicError as exc:
        return False, f"Anthropic API request failed: {type(exc).__name__}"

    return True, None
