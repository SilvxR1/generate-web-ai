"""Preview-traffic detection for the anonymous public endpoints (A8.3.4.2a).

A draft preview is the EXACT artifact that will later be published, so its
lead form and analytics beacon call the real production API. Requests from a
preview deployment must not create leads, notifications, n8n dispatches or
analytics events. The artifact is never altered to achieve this; instead the
server recognizes the browser's `Origin` — every preview is served from the
dedicated preview Pages project (app.publishing.cloudflare.engine
.PREVIEW_PROJECT_NAME), whose hosts are `<project>.pages.dev` and its
subdomains (`<hash>.<project>.pages.dev`, `<branch>.<project>.pages.dev`).

Exact hostname parsing, never substring matching: lookalikes such as
`gwa-draft-previews.pages.dev.attacker.com` are NOT previews. A missing or
unparseable Origin is treated as non-preview (existing behavior unchanged).
This is a suppression signal, not an authentication control: forging a
preview Origin can only suppress the forger's own submission.
"""

from urllib.parse import urlsplit

from app.publishing.cloudflare.engine import PREVIEW_PROJECT_NAME

_PREVIEW_ROOT = f"{PREVIEW_PROJECT_NAME}.pages.dev"


def is_preview_origin(origin: str | None) -> bool:
    if not origin or origin == "null":
        return False
    try:
        parts = urlsplit(origin.strip())
        host = parts.hostname  # lowercased, port and userinfo stripped
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return False
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return False
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return False
    return host == _PREVIEW_ROOT or host.endswith("." + _PREVIEW_ROOT)
