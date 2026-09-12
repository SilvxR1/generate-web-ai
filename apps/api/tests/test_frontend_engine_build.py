"""app.creative.frontend_engine.build — a REAL `npm install` + `astro
build` against a small, fixed (non-AI, fake-manifest) generated project,
proving the generative build pipeline itself works end to end without
spending any Anthropic/Higgsfield credits. The dedicated real-provider
integration test (tests/test_frontend_engine_real.py, `-m real_provider`)
additionally exercises the real Anthropic call on top of this same real
build path — this test isolates and always runs (default CI) the
build/PlatformContract half, which needs no external paid API.
"""

from app.creative.frontend_engine.build import GenerativeBuildError, build_generative_workspace
from app.creative.frontend_engine.legal_pages import build_legal_pages
from app.creative.frontend_engine.manifest import GeneratedFile, GeneratedProjectManifest
from app.creative.frontend_engine.templates import ASTRO_CONFIG, TSCONFIG, build_package_json
from app.creative.frontend_engine.workspace import allocate_workspace, cleanup_workspace, write_manifest
from app.domain.business_config import BusinessConfig, BusinessProfile
from app.domain.enums import BusinessVertical
from app.qa.platform_contract import validate_platform_contract

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
  </head>
  <body>
    <slot />
    <footer>
      <a href="/privacy">Privacy</a>
      <a href="/terms">Terms</a>
      <a href="/cookies">Cookies</a>
    </footer>
  </body>
</html>
"""

_INDEX = """---
import Layout from "../layouts/Layout.astro";
---
<Layout title="Test Business" description="A real test build">
  <main>
    <h1 id="top">Test Business</h1>
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
        business_profile=BusinessProfile(
            name="Real Build Test Co", slug="real-build-test-co", industry=BusinessVertical.OTHER
        )
    )


def test_real_npm_install_and_astro_build_produce_a_valid_static_site():
    workspace = allocate_workspace()
    try:
        manifest = GeneratedProjectManifest(
            files=[
                GeneratedFile(path="src/layouts/Layout.astro", content=_LAYOUT),
                GeneratedFile(path="src/pages/index.astro", content=_INDEX),
            ]
        )
        package_json = build_package_json(name="real-build-test", additional_dependencies=[])
        write_manifest(workspace, manifest, package_json=package_json, astro_config=ASTRO_CONFIG, tsconfig=TSCONFIG)
        for relative_path, content in build_legal_pages(_business_config()).items():
            page_path = workspace / relative_path
            page_path.parent.mkdir(parents=True, exist_ok=True)
            page_path.write_text(content, encoding="utf-8")

        artifact = build_generative_workspace(
            workspace, business_id="test-business-id", api_base_url="https://api.example.com"
        )

        assert "index.html" in artifact.files
        assert "privacy/index.html" in artifact.files or "privacy.html" in artifact.files
        html = artifact.files["index.html"].decode("utf-8")
        assert "platform-config" in html  # server-injected tenant identity
        assert '"businessId": "test-business-id"' in html

        result = validate_platform_contract(artifact.files, business_config=_business_config())
        assert result.passed, [f.message for f in result.blocking_violations]
    finally:
        cleanup_workspace(workspace)


def test_a_build_with_no_package_json_fails_honestly():
    workspace = allocate_workspace()
    try:
        try:
            build_generative_workspace(workspace, business_id="x")
            raise AssertionError("expected GenerativeBuildError")
        except GenerativeBuildError:
            pass
    finally:
        cleanup_workspace(workspace)
