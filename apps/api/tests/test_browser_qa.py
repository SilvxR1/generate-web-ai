"""Real browser QA (P2 continuation Part 3) against a real generative
build's actual static output — Playwright/Chromium, headless, serving
the build over a local HTTP server. Verified to actually launch in this
environment (unlike Chrome DevTools MCP's browser, which could not) via
`playwright install chromium` + `--no-sandbox`.
"""

from app.creative.frontend_engine.browser_qa import run_browser_qa
from app.creative.frontend_engine.build import build_generative_workspace
from app.creative.frontend_engine.legal_pages import build_legal_pages
from app.creative.frontend_engine.manifest import GeneratedFile, GeneratedProjectManifest
from app.creative.frontend_engine.templates import ASTRO_CONFIG, TSCONFIG, build_package_json
from app.creative.frontend_engine.workspace import allocate_workspace, cleanup_workspace, write_manifest
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.enums import BusinessVertical

_LAYOUT = """---
export interface Props { title: string; description: string; }
const { title, description } = Astro.props;
import "../lib/platform-sdk";
---
<html lang="en">
  <head>
    <title>{title}</title>
    <meta name="description" content={description} />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      @media (prefers-reduced-motion: no-preference) {
        .pulse { animation: pulse 2s infinite; }
      }
      @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }
    </style>
  </head>
  <body>
    <slot />
    <footer>
      <a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="/cookies">Cookies</a>
    </footer>
  </body>
</html>
"""

_INDEX = """---
import Layout from "../layouts/Layout.astro";
---
<Layout title="Browser QA Test" description="A real browser QA test build">
  <main>
    <h1 id="top" class="pulse">Browser QA Test</h1>
    <img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBTAA7" alt="test" />
    <a href="#contact">Go to contact</a>
    <section id="contact">
      <form data-gwa-lead-form>
        <input name="name" />
        <button type="submit">Send</button>
      </form>
    </section>
  </main>
  <script>
    import { submitLead } from "../lib/platform-sdk";
    document.querySelector("form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      await submitLead({ name: "test" });
    });
  </script>
</Layout>
"""


def _business_config() -> BusinessConfig:
    return BusinessConfig(
        business_profile=BusinessProfile(name="Browser QA Co", slug="browser-qa-co", industry=BusinessVertical.OTHER)
    )


def _real_build_files() -> dict[str, bytes]:
    workspace = allocate_workspace()
    try:
        manifest = GeneratedProjectManifest(
            files=[
                GeneratedFile(path="src/layouts/Layout.astro", content=_LAYOUT),
                GeneratedFile(path="src/pages/index.astro", content=_INDEX),
            ]
        )
        package_json = build_package_json(name="browser-qa-test", additional_dependencies=[])
        write_manifest(workspace, manifest, package_json=package_json, astro_config=ASTRO_CONFIG, tsconfig=TSCONFIG)
        for relative_path, content in build_legal_pages(_business_config()).items():
            page_path = workspace / relative_path
            page_path.parent.mkdir(parents=True, exist_ok=True)
            page_path.write_text(content, encoding="utf-8")
        artifact = build_generative_workspace(workspace, business_id="browser-qa-test", api_base_url=None)
        return artifact.files
    finally:
        cleanup_workspace(workspace)


def test_real_browser_qa_against_a_real_generative_build():
    files = _real_build_files()

    result = run_browser_qa(files)

    failures = [(f.viewport, f.check, f.detail) for f in result.failures]
    assert result.passed, failures

    # Every required viewport was actually exercised, plus the
    # reduced-motion pass.
    viewports_checked = {f.viewport for f in result.findings}
    assert viewports_checked == {"desktop", "tablet", "mobile", "desktop-reduced-motion"}


def test_browser_qa_detects_a_broken_image():
    files = _real_build_files()
    broken_html = (
        files["index.html"]
        .decode()
        .replace(
            'src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBTAA7"',
            'src="/does-not-exist.png"',
        )
    )
    files = {**files, "index.html": broken_html.encode()}

    result = run_browser_qa(files, viewports=(("desktop", 1440, 900),))

    broken_image_findings = [f for f in result.findings if f.check == "no_broken_images"]
    assert any(not f.passed for f in broken_image_findings)


def test_browser_qa_detects_horizontal_overflow():
    files = _real_build_files()
    overflowing = files["index.html"].decode().replace("</head>", "<style>body { width: 3000px; }</style></head>")
    files = {**files, "index.html": overflowing.encode()}

    result = run_browser_qa(files, viewports=(("mobile", 390, 844),))

    overflow_findings = [f for f in result.findings if f.check == "no_horizontal_overflow"]
    assert any(not f.passed for f in overflow_findings)
