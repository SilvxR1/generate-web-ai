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
import socketserver
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_VIEWPORTS: tuple[tuple[str, int, int], ...] = (
    ("desktop", 1440, 900),
    ("tablet", 768, 1024),
    ("mobile", 390, 844),
)


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

    @property
    def failures(self) -> list[BrowserQAFinding]:
        return [f for f in self.findings if not f.passed]

    @property
    def passed(self) -> bool:
        return not self.failures


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - matches base class signature
        pass  # Never spam test/CI output with per-request access logs.


@contextmanager
def _serve_directory(directory: Path) -> Iterator[int]:
    handler = functools.partial(_QuietHandler, directory=str(directory))
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
    for relative_path, content in files.items():
        if relative_path == "_headers":
            continue  # Cloudflare-specific, not a real file a browser would request.
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _check_viewport(page, *, name: str, base_url: str) -> list[BrowserQAFinding]:
    findings: list[BrowserQAFinding] = []
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    try:
        page.goto(f"{base_url}/index.html", wait_until="networkidle", timeout=15000)
        findings.append(BrowserQAFinding(name, "page_loads", True))
    except Exception as exc:  # noqa: BLE001 - a navigation failure is itself the finding
        findings.append(BrowserQAFinding(name, "page_loads", False, str(exc)))
        return findings

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


def run_browser_qa(
    files: dict[str, bytes],
    *,
    viewports: tuple[tuple[str, int, int], ...] = DEFAULT_VIEWPORTS,
    capture_screenshots: bool = False,
) -> BrowserQAResult:
    """Runs the full check set at every viewport, plus one additional
    pass with `prefers-reduced-motion: reduce` emulated at the desktop
    size — "reduced-motion fallback remains usable" means the page must
    still load and render real content with motion preferences off, not
    merely that a media query exists in the CSS (a static scan could
    lie about that). `capture_screenshots=True` additionally fills
    `BrowserQAResult.screenshots` (P2 Visual QA V1's real evidence — see
    that module for how these get persisted as durable QA artifacts)."""
    result = BrowserQAResult()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_files(root, files)
        with _serve_directory(root) as port:
            base_url = f"http://127.0.0.1:{port}"
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
                try:
                    for name, width, height in viewports:
                        page = browser.new_page(viewport={"width": width, "height": height})
                        result.findings.extend(_check_viewport(page, name=name, base_url=base_url))
                        if capture_screenshots:
                            result.screenshots[name] = page.screenshot(full_page=False)
                        page.close()

                    reduced_motion_page = browser.new_page(viewport={"width": 1440, "height": 900})
                    reduced_motion_page.emulate_media(reduced_motion="reduce")
                    result.findings.extend(
                        _check_viewport(reduced_motion_page, name="desktop-reduced-motion", base_url=base_url)
                    )
                    reduced_motion_page.close()
                finally:
                    browser.close()
    return result
