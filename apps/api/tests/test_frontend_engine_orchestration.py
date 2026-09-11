"""AnthropicFrontendEngine.generate() orchestration, end to end, with a
FAKE manifest-generation client (no network call) but a REAL npm
install + astro build + PlatformContract validation + durable-storage
archive — proves every step *except* the actual Anthropic network call
is wired correctly. The actual-network-call step is covered separately
by tests/test_frontend_engine_real.py (`-m real_provider`); see this
session's final report for why that test could not be run live in this
environment (the configured ANTHROPIC_API_KEY is invalid — confirmed via
a real 401 from Anthropic itself, not a transient error).
"""

from app.creative.frontend_engine.anthropic_engine import AnthropicFrontendEngine
from app.creative.frontend_engine.manifest import GeneratedFile, GeneratedProjectManifest
from app.domain.business_config.examples import EXAMPLE_REFORMA_VALENCIA_CONFIG
from app.domain.creative.direction import (
    ContentStrategy,
    CreativeConcept,
    CreativeDirection,
    ExperienceDirection,
    VisualLanguage,
)
from app.qa.platform_contract import validate_platform_contract
from app.storage import LocalStorageProvider

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
      <a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="/cookies">Cookies</a>
    </footer>
  </body>
</html>
"""

_INDEX = """---
import Layout from "../layouts/Layout.astro";
---
<Layout title="Reforma Casa Valencia" description="Reformas integrales en Valencia">
  <main>
    <h1 id="top">Reforma Casa Valencia</h1>
    <a href="#contacto">Contactar</a>
    <section id="contacto">
      <form data-gwa-lead-form>
        <input name="name" /><button type="submit">Enviar</button>
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


class _FakeManifestClient:
    """Satisfies AnthropicManifestClient's structural shape
    (`generate_manifest(*, system, user_content) -> GeneratedProjectManifest`)
    without any network call — the same fake-injectable-client pattern
    app.analysis.claude.client.AnthropicStructuredOutputClient's own
    tests already use for AnthropicBusinessAnalyzer."""

    def generate_manifest(self, *, system: str, user_content: str) -> GeneratedProjectManifest:
        assert "Reforma Casa Valencia" in user_content  # the real prompt really carries business facts
        return GeneratedProjectManifest(
            files=[
                GeneratedFile(path="src/layouts/Layout.astro", content=_LAYOUT),
                GeneratedFile(path="src/pages/index.astro", content=_INDEX),
            ]
        )


def _direction() -> CreativeDirection:
    return CreativeDirection(
        concept=CreativeConcept(name="test", rationale="test", narrative="test"),
        visual_language=VisualLanguage(
            mood="m",
            palette_direction="p",
            typography_direction="t",
            composition_philosophy="c",
            imagery_treatment="i",
            graphic_language="g",
        ),
        experience=ExperienceDirection(
            navigation_concept="n", storytelling_model="s", responsive_adaptation="r"
        ),
        content_strategy=ContentStrategy(hierarchy="h", primary_user_journey="j", conversion_strategy="lead_capture"),
    )


def test_generate_orchestrates_dependency_check_build_and_durable_archive(tmp_path):
    storage = LocalStorageProvider(root_dir=tmp_path / "uploads")
    engine = AnthropicFrontendEngine(_FakeManifestClient(), storage=storage)  # type: ignore[arg-type]

    result = engine.generate(
        business_config=EXAMPLE_REFORMA_VALENCIA_CONFIG,
        creative_direction=_direction(),
        assets=[],
        platform_contract_version="1.0.0",
        business_id="reforma-orchestration-test",
        api_base_url="https://api.example.com",
    )

    assert "index.html" in result.artifact.files
    assert result.framework == "astro"
    assert result.generator_provider == "anthropic"

    # Durable archive really exists on the configured StorageProvider —
    # not an ephemeral /tmp path.
    archived_path = tmp_path / "uploads" / result.workspace_key
    assert archived_path.is_file()

    contract = validate_platform_contract(result.artifact.files, business_config=EXAMPLE_REFORMA_VALENCIA_CONFIG)
    assert contract.passed, [f.message for f in contract.blocking_violations]
