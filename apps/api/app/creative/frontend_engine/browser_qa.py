"""run_browser_qa — P2 continuation Part 3: real browser QA against a
real generative build's actual static output, using Playwright/Chromium
(the project's now-verified browser tooling — Chrome DevTools MCP's
browser could not launch in this environment; Playwright's bundled
Chromium does, with `--no-sandbox`).

Serves the build's real files over a plain local HTTP server (the same
"reversible, temp-directory, no external network" shape every other
throwaway artifact in this codebase uses) and drives a real headless
Chromium against it at each required viewport (1440x900, 768x1024,
390x844 — P2's desktop/tablet/mobile set). Every check is a real,
in-browser assertion — not a static-HTML regex scan (that's
app.qa.platform_contract's job, which already covers the CTA/anchor/
lead-form-wiring checks statelessly); this module is what proves the
build actually *runs* correctly in a real browser: no critical console
errors, no broken images, no horizontal overflow, working navigation/
CTA/form interaction, and a real check that page rendering doesn't
depend on motion (`prefers-reduced-motion: reduce` emulated).
"""

import functools
import http.server
import mimetypes
import socketserver
import tempfile
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_VIEWPORTS: tuple[tuple[str, int, int], ...] = (
    ("desktop", 1440, 900),
    ("tablet", 768, 1024),
    ("mobile", 390, 844),
)


class BrowserQAUnavailableError(Exception):
    """Real browser/Visual QA (Playwright + Chromium) could not run in
    this runtime — either the `playwright` package isn't installed or
    Chromium couldn't launch. Deliberately never caught and turned into a
    quiet pass/skip anywhere in this codebase (P2's "no silent
    degradation" rule): every caller either lets this propagate as an
    explicit failure or maps it to one (see
    app.publishing.drafts.run_visual_qa_for_draft). `playwright` is
    imported lazily inside run_browser_qa specifically so *this* error is
    what a caller sees on a broken browser-QA runtime, instead of the
    whole FastAPI app failing to boot from a module-level ImportError —
    see this module's own docstring and Dockerfile.prod for how
    production actually installs Playwright + Chromium."""


@dataclass
class BrowserQAFinding:
    viewport: str
    check: str
    passed: bool
    detail: str = ""


@dataclass
class BrowserQAResult:
    findings: list[BrowserQAFinding] = field(default_factory=list)
    # {viewport_name: PNG bytes} — only populated when
    # run_browser_qa(capture_screenshots=True) — the real evidence P2's
    # Visual QA V1 persists, never generated when a caller only wants
    # the pass/fail findings (screenshots cost real time/space to keep).
    screenshots: dict[str, bytes] = field(default_factory=dict)
    # v0.2 R4.1: with `offline_assets`, every request that is neither the
    # local site nor a supplied asset is aborted and listed here.
    blocked_requests: list[str] = field(default_factory=list)
    # Results of `probe_script` per page (test/acceptance evidence only).
    probes: list[object] = field(default_factory=list)

    @property
    def failures(self) -> list[BrowserQAFinding]:
        return [f for f in self.findings if not f.passed]

    @property
    def passed(self) -> bool:
        return not self.failures


HEADERS_FILE = "_headers"
_CSP_VIOLATION_WATCH = (
    "window.__gwaCspViolations = [];"
    "document.addEventListener('securitypolicyviolation', e => window.__gwaCspViolations.push("
    "e.effectiveDirective + ' ' + (e.blockedURI || 'inline')));"
)


def parse_headers_file(content: bytes) -> list[tuple[str, str]]:
    """The `/*` rules of a Cloudflare Pages `_headers` file — the policy the
    host applies to every route of the site."""
    headers: list[tuple[str, str]] = []
    in_all = False
    for line in content.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            in_all = line.strip() == "/*"
            continue
        if in_all and ":" in line:
            name, value = line.strip().split(":", 1)
            headers.append((name.strip(), value.strip()))
    return headers


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """H1.1: serves the site like its host does — the artifact's own
    `_headers` (CSP included) on every response, and `_headers` itself is
    never served as a file."""

    site_headers: list[tuple[str, str]] = []

    def send_head(self):  # overrides SimpleHTTPRequestHandler.send_head
        if self.path.split("?", 1)[0].split("#", 1)[0].rstrip("/").endswith("/" + HEADERS_FILE):
            self.send_error(404)
            return None
        return super().send_head()

    def end_headers(self) -> None:
        for name, value in self.site_headers:
            self.send_header(name, value)
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - matches base class signature
        pass  # Never spam test/CI output with per-request access logs.


@contextmanager
def _serve_directory(directory: Path) -> Iterator[int]:
    headers_file = directory / HEADERS_FILE
    site_headers = parse_headers_file(headers_file.read_bytes()) if headers_file.is_file() else []
    handler_class = type("_SiteHandler", (_QuietHandler,), {"site_headers": site_headers})
    handler = functools.partial(handler_class, directory=str(directory))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield port
        finally:
            httpd.shutdown()
            thread.join(timeout=5)


def _write_files(root: Path, files: dict[str, bytes]) -> None:
    # `_headers` is written too: _serve_directory applies it (never serves it),
    # so Visual QA exercises the exact policy the host will apply (H1.1).
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _check_viewport(page, *, name: str, base_url: str, expected_csp: str | None = None) -> list[BrowserQAFinding]:
    findings: list[BrowserQAFinding] = []
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    # H1.1: same-origin resources that failed (the implicit favicon probe is
    # not a site resource).
    failed: list[str] = []
    page.on(
        "response",
        lambda r: failed.append(f"{r.status} {r.url}")
        if r.status >= 400 and r.url.startswith(base_url) and not r.url.endswith("/favicon.ico")
        else None,
    )
    page.on("requestfailed", lambda r: failed.append(f"failed {r.url}") if r.url.startswith(base_url) else None)

    try:
        # "/" — the URL a visitor loads (static hosts serve index.html for it
        # and redirect /index.html to it). A client-side router (H1: TanStack
        # Start prerendered pages) treats /index.html as a different route.
        response = page.goto(f"{base_url}/", wait_until="networkidle", timeout=15000)
        findings.append(BrowserQAFinding(name, "page_loads", True))
    except Exception as exc:  # noqa: BLE001 - a navigation failure is itself the finding
        findings.append(BrowserQAFinding(name, "page_loads", False, str(exc)))
        return findings

    # H1.1: the page ran under the artifact's OWN policy, and broke none of it.
    if expected_csp is not None:
        served = response.headers.get("content-security-policy") if response is not None else None
        findings.append(BrowserQAFinding(name, "artifact_csp_applied", served == expected_csp, str(served)[:200]))
    violations = page.evaluate("window.__gwaCspViolations || []")
    findings.append(BrowserQAFinding(name, "no_csp_violations", not violations, "; ".join(violations)[:500]))
    findings.append(BrowserQAFinding(name, "no_failed_resources", not failed, "; ".join(failed)[:500]))

    # No critical console/page errors.
    findings.append(
        BrowserQAFinding(name, "no_console_errors", not console_errors, "; ".join(console_errors)[:500])
    )
    findings.append(BrowserQAFinding(name, "no_uncaught_page_errors", not page_errors, "; ".join(page_errors)[:500]))

    # No broken images.
    broken_images = page.eval_on_selector_all(
        "img", "imgs => imgs.filter(i => !i.complete || i.naturalWidth === 0).map(i => i.src)"
    )
    findings.append(BrowserQAFinding(name, "no_broken_images", len(broken_images) == 0, "; ".join(broken_images)))

    # No horizontal overflow.
    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
    findings.append(BrowserQAFinding(name, "no_horizontal_overflow", not overflow))

    # Main content is actually visible, not a blank page.
    has_visible_content = page.evaluate(
        "document.body.innerText.trim().length > 0 || document.querySelectorAll('svg, img, canvas').length > 0"
    )
    findings.append(BrowserQAFinding(name, "has_visible_content", has_visible_content))

    # A real primary heading exists with visible text — catches a page
    # that renders *something* (so has_visible_content passes) but never
    # actually generated a hero/primary content section, only chrome
    # like a nav bar or footer.
    has_primary_heading = page.evaluate(
        "Array.from(document.querySelectorAll('h1')).some(h => h.innerText.trim().length > 0)"
    )
    findings.append(BrowserQAFinding(name, "has_primary_heading", has_primary_heading))

    # A lead form (if present) accepts real input.
    if page.query_selector("form[data-gwa-lead-form] input"):
        first_input = page.query_selector("form[data-gwa-lead-form] input")
        first_input.fill("QA test value")
        value = first_input.input_value()
        findings.append(BrowserQAFinding(name, "form_accepts_input", value == "QA test value"))
    else:
        findings.append(BrowserQAFinding(name, "form_accepts_input", True, "no lead form on this page"))

    # Internal anchors resolve to a real element with no navigation error.
    anchor_hrefs = page.eval_on_selector_all(
        "a[href^='#']", "as => as.map(a => a.getAttribute('href')).filter(h => h.length > 1)"
    )
    broken_anchors = [href for href in anchor_hrefs if not page.query_selector(href)]
    findings.append(BrowserQAFinding(name, "internal_anchors_resolve", not broken_anchors, "; ".join(broken_anchors)))

    return findings


def check_browser_qa_availability() -> tuple[bool, str | None]:
    """Cheap, non-billable readiness check for the P2 capability endpoint
    (P2.1) — never launches a real browser (that's what run_browser_qa
    itself does): only confirms the `playwright` package imports and that
    a Chromium executable actually exists on disk at the path Playwright
    would launch, mirroring run_browser_qa's own lazy-import discipline so
    a broken runtime here can never crash the whole app either. Returns
    (available, unavailable_reason), never raises."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "The playwright package is not installed in this runtime."

    try:
        with sync_playwright() as playwright:
            executable_path = playwright.chromium.executable_path
            if not executable_path or not Path(executable_path).is_file():
                return False, f"Chromium is not installed at the expected path ({executable_path or 'unknown'})."
    except Exception as exc:  # noqa: BLE001 — any driver-startup failure is itself the finding here
        return False, f"Could not start the Playwright driver: {type(exc).__name__}"
    return True, None


def _offline_router(base_url: str, offline_assets: Mapping[str, bytes], blocked: list[str]) -> Callable[..., None]:
    """v0.2 R4.1: the page may load only the local site and the business's
    own assets (supplied by trusted code, never fetched from inside the
    sandbox); everything else is aborted — defense in depth on top of the
    sandbox's network namespace."""

    def handle(route: Any) -> None:
        url = route.request.url
        if url.startswith(base_url + "/"):
            route.continue_()
        elif url in offline_assets:
            content_type = mimetypes.guess_type(url.split("?", 1)[0])[0] or "application/octet-stream"
            route.fulfill(status=200, body=offline_assets[url], headers={"content-type": content_type})
        else:
            if len(blocked) < 200:
                blocked.append(url[:300])
            route.abort()

    return handle


def run_browser_qa(
    files: dict[str, bytes],
    *,
    viewports: tuple[tuple[str, int, int], ...] = DEFAULT_VIEWPORTS,
    capture_screenshots: bool = False,
    offline_assets: Mapping[str, bytes] | None = None,
    probe_script: str | None = None,
) -> BrowserQAResult:
    """Runs the full check set at every viewport, plus one additional
    pass with `prefers-reduced-motion: reduce` emulated at the desktop
    size — "reduced-motion fallback remains usable" means the page must
    still load and render real content with motion preferences off, not
    merely that a media query exists in the CSS (a static scan could
    lie about that). `capture_screenshots=True` additionally fills
    `BrowserQAResult.screenshots` (P2 Visual QA V1's real evidence — see
    that module for how these get persisted as durable QA artifacts).

    Raises BrowserQAUnavailableError (never a bare ImportError/Playwright
    Error) if Playwright isn't installed or Chromium can't launch in this
    runtime — see that exception's own docstring for why the import is
    deferred to here instead of living at module level."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserQAUnavailableError(
            "The playwright package is not installed in this runtime — real browser/Visual QA is unavailable."
        ) from exc

    result = BrowserQAResult()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_files(root, files)
        policy = dict(parse_headers_file(files[HEADERS_FILE])) if HEADERS_FILE in files else {}
        expected_csp = policy.get("Content-Security-Policy")
        with _serve_directory(root) as port:
            base_url = f"http://127.0.0.1:{port}"
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
                except PlaywrightError as exc:
                    raise BrowserQAUnavailableError(
                        f"Chromium could not be launched — real browser/Visual QA is unavailable: {exc}"
                    ) from exc
                context = browser.new_context()
                # H1.1: every CSP violation the artifact's own policy reports.
                context.add_init_script(_CSP_VIOLATION_WATCH)
                if offline_assets is not None:
                    context.route("**/*", _offline_router(base_url, offline_assets, result.blocked_requests))
                try:
                    for name, width, height in viewports:
                        page = context.new_page()
                        page.set_viewport_size({"width": width, "height": height})
                        result.findings.extend(
                            _check_viewport(page, name=name, base_url=base_url, expected_csp=expected_csp)
                        )
                        if probe_script is not None:
                            page.wait_for_timeout(1500)
                            result.probes.append(page.evaluate(probe_script))
                        if capture_screenshots:
                            result.screenshots[name] = page.screenshot(full_page=False)
                        page.close()

                    reduced_motion_page = context.new_page()
                    reduced_motion_page.set_viewport_size({"width": 1440, "height": 900})
                    reduced_motion_page.emulate_media(reduced_motion="reduce")
                    result.findings.extend(
                        _check_viewport(
                            reduced_motion_page,
                            name="desktop-reduced-motion",
                            base_url=base_url,
                            expected_csp=expected_csp,
                        )
                    )
                    reduced_motion_page.close()
                finally:
                    browser.close()
    return result
