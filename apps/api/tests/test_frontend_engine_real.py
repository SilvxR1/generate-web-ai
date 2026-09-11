"""REAL, non-mocked end-to-end proof of the Generative Frontend Engine
(P2 Part C's "do not mock the build in the main integration test"):
real Anthropic API call -> real npm install + astro build -> real
PlatformContract validation. Marked `real_provider` and excluded from
the default `pytest` invocation (see pyproject.toml's addopts) — run
explicitly with `pytest -m real_provider tests/test_frontend_engine_real.py`.

Deliberately spends ZERO new Higgsfield credits: the CreativeDirection
used here is the actual, already-generated, already-paid-for result of
this P2 task's real Higgsfield end-to-end run (see
tests/fixtures/reforma_creative_direction.json — extracted verbatim from
that run's own output, including its real Higgsfield job id and
CloudFront result URLs). Only real Anthropic tokens are spent, which
this task's credit budget does not restrict.
"""

import json
from pathlib import Path

import anthropic
import pytest

from app.config import settings
from app.creative.frontend_engine.anthropic_engine import AnthropicFrontendEngine
from app.creative.frontend_engine.client import AnthropicManifestClient
from app.domain.business_config.examples import EXAMPLE_REFORMA_VALENCIA_CONFIG
from app.domain.creative.direction import CreativeDirection
from app.qa.platform_contract import validate_platform_contract
from app.storage import LocalStorageProvider

pytestmark = pytest.mark.real_provider

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "reforma_creative_direction.json"


def _real_reforma_direction() -> CreativeDirection:
    return CreativeDirection.model_validate(json.loads(_FIXTURE_PATH.read_text()))


@pytest.mark.skipif(not settings.anthropic_api_key, reason="ANTHROPIC_API_KEY not configured")
def test_real_anthropic_engine_produces_a_publishable_bespoke_site(tmp_path):
    direction = _real_reforma_direction()
    storage = LocalStorageProvider(root_dir=tmp_path / "uploads")
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    engine = AnthropicFrontendEngine(AnthropicManifestClient(client, model=settings.anthropic_model), storage=storage)

    result = engine.generate(
        business_config=EXAMPLE_REFORMA_VALENCIA_CONFIG,
        creative_direction=direction,
        assets=[],
        platform_contract_version="1.0.0",
        business_id="real-reforma-test",
        api_base_url="https://api.example.com",
    )

    assert "index.html" in result.artifact.files
    assert result.generator_provider == "anthropic"
    assert result.duration_ms > 0
    # The generated source was archived durably (not left as a /tmp path).
    assert storage._resolve(result.workspace_key).is_file()  # noqa: SLF001 — verifying the real durable artifact exists

    contract = validate_platform_contract(result.artifact.files, business_config=EXAMPLE_REFORMA_VALENCIA_CONFIG)
    assert contract.passed, [f.message for f in contract.blocking_violations]

    # Bespoke, not deterministic: the generated homepage must not be the
    # deterministic engine's own block markup (no "block-contact__form"
    # class, no packages/blocks component signatures) — real, AI-authored
    # structure instead.
    index_html = result.artifact.files["index.html"].decode("utf-8", errors="ignore")
    assert "block-contact__form" not in index_html
    assert "data-gwa-lead-form" in index_html
