"""check_higgsfield_director_availability — the ONE authoritative,
real-verified P2 Higgsfield Creative Director availability check (P2.1),
mirroring app.creative.frontend_engine.availability.check_frontend_engineer_availability's
same "configured means working, not just present" discipline for Anthropic.

Never spends a Higgsfield credit: probes `GET /requests/<a made-up
UUID>/status`, a real, read-only, unbilled lookup. Higgsfield returns 401
Unauthorized if the API key pair is rejected, or a normal (non-401)
response — typically 404, since the id was never submitted — once
authentication itself succeeds. Either non-401 outcome proves the key pair
is genuinely accepted, not merely "a string is present"; only a definite
401, a connection failure, or missing configuration report unavailable.
"""

import uuid

import httpx

from app.config import Settings


def check_higgsfield_director_availability(settings: Settings) -> tuple[bool, str | None]:
    """Returns (available, unavailable_reason). Never raises — every
    failure mode (no key pair configured, key pair rejected, network
    error) is reported as `(False, <reason>)`; the key secret itself is
    never included in the reason or logged anywhere in this call path."""
    if not settings.higgsfield_api_key_id or not settings.higgsfield_api_key_secret:
        return False, "HIGGSFIELD_API_KEY_ID/HIGGSFIELD_API_KEY_SECRET are not configured on this server."

    headers = {"Authorization": f"Key {settings.higgsfield_api_key_id}:{settings.higgsfield_api_key_secret}"}
    probe_path = f"/requests/{uuid.uuid4()}/status"
    try:
        response = httpx.get(
            f"{settings.higgsfield_api_base_url}{probe_path}",
            headers=headers,
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        )
    except httpx.HTTPError as exc:
        return False, f"Could not reach the Higgsfield API: {type(exc).__name__}"

    if response.status_code == 401:
        return (
            False,
            "HIGGSFIELD_API_KEY_ID/HIGGSFIELD_API_KEY_SECRET were rejected by Higgsfield (invalid or revoked).",
        )
    return True, None
