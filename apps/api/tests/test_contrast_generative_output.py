"""P2 Part I — the contrast test: proves the generative pipeline does not
collapse two different businesses into the same structural template.

Runs BOTH golden fixtures (Reforma Valencia — home renovation, real
Higgsfield-explored "bespoke visual metaphor" direction; Cositas y
Puntos — handmade crochet, real Higgsfield-explored "immersive scene
with thread-path navigation" direction, reconstructed from real prior
job history, zero new credits) through AnthropicFrontendEngine.generate(),
through a REAL npm+astro build, through real PlatformContract validation,
and asserts the two outputs differ structurally — navigation model,
component/DOM structure, asset/interaction treatment — not merely in
color/font.

Honest scope note: the real ANTHROPIC_API_KEY in this environment is
confirmed invalid (see tests/test_frontend_engine_real.py's docstring),
so the actual LLM decision itself could not be exercised live for this
comparison. The two manifest-generation clients below are fake,
hand-authored to faithfully reflect each fixture's own CreativeDirection
fields (different navigation_concept, different interaction_concepts) —
this proves the *pipeline* supports and enforces genuine structural
divergence end to end (real build, real contract, both engines fed
identical BusinessConfig/CreativeDirection/PlatformContract inputs
through the identical code path), not that a live model chose to
diverge. See the session's final report for what a real API key would
additionally prove.
"""

import json
from pathlib import Path

from app.creative.frontend_engine.anthropic_engine import AnthropicFrontendEngine
from app.creative.frontend_engine.manifest import GeneratedFile, GeneratedProjectManifest
from app.domain.business_config.examples import EXAMPLE_COSITAS_Y_PUNTOS_CONFIG, EXAMPLE_REFORMA_VALENCIA_CONFIG
from app.domain.creative.direction import CreativeDirection
from app.qa.platform_contract import validate_platform_contract
from app.storage import LocalStorageProvider

_FIXTURES = Path(__file__).parent / "fixtures"

_LAYOUT_TEMPLATE = """---
export interface Props {{ title: string; description: string; }}
const {{ title, description }} = Astro.props;
import "../lib/platform-sdk";
---
<html lang="en">
  <head>
    <title>{{title}}</title>
    <meta name="description" content={{description}} />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    {nav}
    <slot />
    <footer>
      <a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="/cookies">Cookies</a>
    </footer>
  </body>
</html>
"""

_REFORMA_INDEX = """---
import Layout from "../layouts/Layout.astro";
---
<Layout title="Reforma Casa Valencia" description="Reformas integrales en Valencia">
  <main class="editorial-grid">
    <section id="servicios" class="services-grid">
      <h1>Reforma Casa Valencia</h1>
      <div class="service-card">Cocinas</div>
      <div class="service-card">Banos</div>
    </section>
    <section id="contacto">
      <form data-gwa-lead-form>
        <input name="name" /><button type="submit">Solicitar presupuesto</button>
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

_COSITAS_INDEX = """---
import Layout from "../layouts/Layout.astro";
---
<Layout title="Cositas y Puntos" description="Amigurumi y crochet hechos a mano">
  <main class="scene-diorama" data-thread-path-scene>
    <svg class="thread-path" viewBox="0 0 100 100" aria-hidden="true">
      <path d="M10 10 L50 50 L90 20" data-thread-glow />
    </svg>
    <div id="creacion-1" class="scene-hotspot" data-hotspot>Ver creacion</div>
    <section id="contacto" class="scene-hotspot" data-hotspot>
      <form data-gwa-lead-form>
        <input name="name" /><button type="submit">Consultar encargo</button>
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


def _fake_client_for(nav_html: str, index_content: str):
    layout = _LAYOUT_TEMPLATE.format(nav=nav_html)

    class _FakeClient:
        def generate_manifest(self, *, system: str, user_content: str) -> GeneratedProjectManifest:
            return GeneratedProjectManifest(
                files=[
                    GeneratedFile(path="src/layouts/Layout.astro", content=layout),
                    GeneratedFile(path="src/pages/index.astro", content=index_content),
                ]
            )

    return _FakeClient()


def _load_direction(name: str) -> CreativeDirection:
    data = json.loads((_FIXTURES / name).read_text())
    data.pop("_provenance", None)
    return CreativeDirection.model_validate(data)


def test_two_golden_fixtures_produce_structurally_different_real_builds(tmp_path):
    reforma_storage = LocalStorageProvider(root_dir=tmp_path / "reforma-uploads")
    cositas_storage = LocalStorageProvider(root_dir=tmp_path / "cositas-uploads")

    reforma_engine = AnthropicFrontendEngine(
        _fake_client_for('<nav class="editorial-nav"><a href="#servicios">Servicios</a></nav>', _REFORMA_INDEX),
        storage=reforma_storage,
    )
    cositas_engine = AnthropicFrontendEngine(
        _fake_client_for(
            "<!-- no conventional navbar: navigation is embedded in the scene itself -->", _COSITAS_INDEX
        ),
        storage=cositas_storage,
    )

    reforma_direction = _load_direction("reforma_creative_direction.json")
    cositas_direction = _load_direction("cositas_creative_direction.json")

    reforma_result = reforma_engine.generate(
        business_config=EXAMPLE_REFORMA_VALENCIA_CONFIG,
        creative_direction=reforma_direction,
        assets=[],
        platform_contract_version="1.0.0",
        business_id="reforma-contrast-test",
        api_base_url="https://api.example.com",
    )
    cositas_result = cositas_engine.generate(
        business_config=EXAMPLE_COSITAS_Y_PUNTOS_CONFIG,
        creative_direction=cositas_direction,
        assets=[],
        platform_contract_version="1.0.0",
        business_id="cositas-contrast-test",
        api_base_url="https://api.example.com",
    )

    # Both real builds must independently satisfy the identical
    # PlatformContract — same contract, different look/feel/structure.
    reforma_contract = validate_platform_contract(
        reforma_result.artifact.files, business_config=EXAMPLE_REFORMA_VALENCIA_CONFIG
    )
    cositas_contract = validate_platform_contract(
        cositas_result.artifact.files, business_config=EXAMPLE_COSITAS_Y_PUNTOS_CONFIG
    )
    assert reforma_contract.passed, [f.message for f in reforma_contract.blocking_violations]
    assert cositas_contract.passed, [f.message for f in cositas_contract.blocking_violations]

    reforma_html = reforma_result.artifact.files["index.html"].decode("utf-8")
    cositas_html = cositas_result.artifact.files["index.html"].decode("utf-8")

    # --- Structural divergence beyond color/font/border-radius/order ---

    # 1. Navigation model: Reforma uses a conventional nav with anchor
    # links; Cositas has none (thread-path-embedded navigation instead).
    assert "editorial-nav" in reforma_html
    assert "editorial-nav" not in cositas_html
    assert "data-thread-path-scene" in cositas_html
    assert "data-thread-path-scene" not in reforma_html

    # 2. Composition/DOM structure: Reforma is a grid of service cards;
    # Cositas is an SVG-based diorama scene with hotspots — genuinely
    # different component architecture, not a reskin of the same markup.
    assert "service-card" in reforma_html and "service-card" not in cositas_html
    assert "<svg" in cositas_html and "data-hotspot" in cositas_html
    assert "<svg" not in reforma_html

    # 3. Both still carry the same platform hooks (proving the contract
    # is genuinely engine/design-agnostic, not just "different enough to
    # pass by accident").
    assert "data-gwa-lead-form" in reforma_html
    assert "data-gwa-lead-form" in cositas_html
