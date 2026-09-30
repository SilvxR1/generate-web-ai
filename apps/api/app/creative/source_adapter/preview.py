"""serve_artifact (H1): a real LOCAL preview of a WebsiteArtifact.

Unlike app.creative.frontend_engine.browser_qa (which drops `_headers`),
this serves the artifact exactly as a static host would: from memory, the
`/*` block of the artifact's own `_headers` applied to every response —
so the real CSP is enforced by the browser and a policy that would break
the site (e.g. blocked blob: video) fails locally, before any publish.
Directory-style URLs resolve like Cloudflare Pages (`/privacy` ->
`privacy/index.html`). Bound to 127.0.0.1 only.
"""

import http.server
import mimetypes
import socketserver
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import unquote, urlsplit

from app.creative.frontend_engine.browser_qa import parse_headers_file
from app.publishing.publisher import WebsiteArtifact

_EXTRA_TYPES = {".woff2": "font/woff2", ".woff": "font/woff", ".webmanifest": "application/manifest+json"}


def resolve_path(files: dict[str, bytes], url_path: str) -> str | None:
    path = unquote(urlsplit(url_path).path).lstrip("/")
    if ".." in path.split("/"):
        return None
    for candidate in (path, f"{path.rstrip('/')}/index.html" if path else "index.html", f"{path}.html"):
        if candidate in files and candidate != "_headers":
            return candidate
    return None


def _content_type(path: str) -> str:
    for suffix, value in _EXTRA_TYPES.items():
        if path.endswith(suffix):
            return value
    guessed = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return f"{guessed}; charset=utf-8" if guessed.startswith("text/") or guessed.endswith(("xml", "json")) else guessed


@contextmanager
def serve_artifact(artifact: WebsiteArtifact, *, port: int = 0) -> Iterator[str]:
    """Yields the base URL (http://127.0.0.1:<port>) while serving."""
    files = artifact.files
    policy = parse_headers_file(files.get("_headers", b""))

    class Handler(http.server.BaseHTTPRequestHandler):
        def _respond(self, body: bool) -> None:
            path = resolve_path(files, self.path)
            if path is None:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                for name, value in policy:
                    self.send_header(name, value)
                self.end_headers()
                if body:
                    self.wfile.write(b"not found")
                return
            data = files[path]
            self.send_response(200)
            self.send_header("Content-Type", _content_type(path))
            self.send_header("Content-Length", str(len(data)))
            for name, value in policy:
                self.send_header(name, value)
            self.end_headers()
            if body:
                self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 — http.server's handler naming
            self._respond(body=True)

        def do_HEAD(self) -> None:  # noqa: N802
            self._respond(body=False)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    with Server(("127.0.0.1", port), Handler) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}"
        finally:
            httpd.shutdown()
            thread.join(timeout=5)
