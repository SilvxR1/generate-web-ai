"""R5.2 — web app manifest validation on the built artifact.

Independent of how a deployment is fronted (the Cloudflare Access-protected
Private Preview cannot prove it: browsers fetch manifests WITHOUT cookies,
so Access redirects that one request). For every `<link rel="manifest">`:

- the URL is same-origin (a root-relative or relative path; no scheme,
  no `//host`, no `data:`): the platform CSP serves manifests from 'self';
- the referenced file exists in the artifact and parses as a JSON object;
- every icon `src` is local and resolves to a file in the artifact;
- the file's serving type, derived from its extension, is standards
  compatible: `.webmanifest` -> application/manifest+json (the type the
  local QA server and Cloudflare Pages use), `.json` -> application/json
  (which browsers accept for manifests); and the artifact's `_headers` does
  not override it with anything else.
"""

import json
import posixpath
import re
from urllib.parse import unquote, urlsplit

ALLOWED_TYPES = {".webmanifest": "application/manifest+json", ".json": "application/json"}
_LINK = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_REL = re.compile(r"""\brel\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)
_HREF = re.compile(r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)
_MAX_PROBLEMS = 20


def _attr(pattern: re.Pattern[str], tag: str) -> str | None:
    m = pattern.search(tag)
    return next((g for g in m.groups() if g is not None), None) if m else None


def _local_path(base_path: str, url: str) -> str | None:
    """The artifact path a same-origin URL names, or None when it is not
    same-origin (scheme, network path, data: ...)."""
    value = url.strip()
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or value.startswith("//") or not parts.path:
        return None
    path = unquote(parts.path)
    joined = path if path.startswith("/") else posixpath.join("/" + posixpath.dirname(base_path), path)
    return posixpath.normpath(joined).lstrip("/")


def _header_content_type(headers: str, path: str) -> str | None:
    """A Content-Type the artifact's `_headers` sets for exactly this path."""
    current: str | None = None
    for raw in headers.splitlines():
        if raw and not raw[0].isspace():
            current = raw.strip()
        elif current == f"/{path}" and raw.strip().lower().startswith("content-type:"):
            return raw.split(":", 1)[1].strip()
    return None


def manifest_links(files: dict[str, bytes]) -> list[tuple[str, str]]:
    """(page, href) for every manifest link in the artifact's HTML."""
    links: list[tuple[str, str]] = []
    for page in sorted(p for p in files if p.endswith(".html")):
        for tag in _LINK.findall(files[page].decode("utf-8", errors="ignore")):
            rel = (_attr(_REL, tag) or "").lower().split()
            href = _attr(_HREF, tag)
            if "manifest" in rel and href is not None:
                links.append((page, href))
    return links


def validate_web_manifests(files: dict[str, bytes]) -> list[str]:
    problems: list[str] = []
    headers = files.get("_headers", b"").decode("utf-8", errors="ignore")
    checked: set[str] = set()
    for page, href in manifest_links(files):
        path = _local_path(page, href)
        if path is None:
            problems.append(f"{page}: manifest {href[:120]!r} is not same-origin (not allowed by platform policy)")
            continue
        if path in checked:
            continue
        checked.add(path)
        if path not in files:
            problems.append(f"{page}: manifest /{path} does not exist in the artifact")
            continue
        extension = posixpath.splitext(path)[1].lower()
        if extension not in ALLOWED_TYPES:
            problems.append(f"/{path}: manifest extension {extension or '(none)'!r} has no standard manifest type")
        override = _header_content_type(headers, path)
        if override is not None and override.split(";")[0].strip().lower() not in ALLOWED_TYPES.values():
            problems.append(f"/{path}: _headers serves the manifest as {override[:80]!r}")
        try:
            data = json.loads(files[path].decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            problems.append(f"/{path}: manifest is not valid JSON")
            continue
        if not isinstance(data, dict):
            problems.append(f"/{path}: manifest is not a JSON object")
            continue
        icons = data.get("icons", [])
        if not isinstance(icons, list):
            problems.append(f"/{path}: manifest 'icons' is not a list")
            continue
        for icon in icons:
            src = icon.get("src") if isinstance(icon, dict) else None
            if not isinstance(src, str) or not src.strip():
                problems.append(f"/{path}: an icon has no src")
                continue
            icon_path = _local_path(path, src)
            if icon_path is None:
                problems.append(f"/{path}: icon {src[:120]!r} is not same-origin")
            elif icon_path not in files:
                problems.append(f"/{path}: icon /{icon_path} does not exist in the artifact")
    return problems[:_MAX_PROBLEMS]
