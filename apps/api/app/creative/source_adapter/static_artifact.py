"""Static artifact assembly (H1): a prerendered static build output becomes
a GWA WebsiteArtifact through the SAME platform steps the generative
engine uses (app.creative.frontend_engine.build):

- collect_candidate_files — bounded, regular files only, no symlinks;
- inject_platform_runtime — server-controlled `platform-config` + the
  platform consent banner, into every page;
- `_headers` — generate_headers_file with the inline-script hashes of the
  final HTML, the public API origin and the source family's trusted
  CspExtensions.

robots.txt and sitemap.xml are platform-owned (like `_headers`): any file of
that name in the build output is discarded and regenerated from the site's
public origin and the pages actually present.
"""

from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from app.creative.frontend_engine.build import collect_candidate_files, inject_platform_runtime, inline_script_hashes
from app.creative.source_adapter.records import AdapterError
from app.publishing.publisher import WebsiteArtifact
from app.publishing.security_headers import CspExtensions, generate_headers_file

PLATFORM_OWNED_FILES = frozenset({"_headers", "robots.txt", "sitemap.xml"})


def _site_origin(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.path not in ("", "/") or parts.query or parts.fragment:
        raise AdapterError(f"the site origin must be a bare https origin: {value!r}")
    return f"https://{parts.netloc.lower()}"


def page_url_path(html_path: str) -> str:
    """index.html -> /, privacy/index.html -> /privacy, about.html -> /about."""
    path = PurePosixPath(html_path)
    if path.name == "index.html":
        parent = path.parent.as_posix()
        return "/" if parent == "." else f"/{parent}"
    return f"/{path.with_suffix('').as_posix()}"


def robots_txt(site_origin: str) -> bytes:
    return f"User-agent: *\nAllow: /\n\nSitemap: {_site_origin(site_origin)}/sitemap.xml\n".encode()


def sitemap_xml(site_origin: str, html_paths: list[str]) -> bytes:
    origin = _site_origin(site_origin)
    urls = sorted({page_url_path(p) for p in html_paths if PurePosixPath(p).name not in ("404.html", "500.html")})
    entries = "".join(f"  <url><loc>{escape(origin + url)}</loc></url>\n" for url in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}</urlset>\n"
    ).encode()


def assemble_static_artifact(
    client_dir: Path,
    *,
    business_id: str,
    api_base_url: str | None,
    site_origin: str,
    csp_extensions: CspExtensions | None,
) -> WebsiteArtifact:
    candidate = collect_candidate_files(client_dir)
    files: dict[str, bytes] = {}
    html_texts: list[str] = []
    for relative, data in sorted(candidate.items()):
        if relative in PLATFORM_OWNED_FILES:
            continue
        if relative.endswith(".html"):
            html = inject_platform_runtime(
                data.decode("utf-8", errors="ignore"), business_id=business_id, api_base_url=api_base_url
            )
            html_texts.append(html)
            files[relative] = html.encode("utf-8")
        else:
            files[relative] = data
    if "index.html" not in files:
        raise AdapterError("the static build has no index.html")
    html_paths = [p for p in files if p.endswith(".html")]
    files["robots.txt"] = robots_txt(site_origin)
    files["sitemap.xml"] = sitemap_xml(site_origin, html_paths)
    files["_headers"] = generate_headers_file(
        script_hashes=inline_script_hashes(html_texts), public_api_origin=api_base_url, csp_extensions=csp_extensions
    )
    return WebsiteArtifact(files=files, entry_point="index.html")
