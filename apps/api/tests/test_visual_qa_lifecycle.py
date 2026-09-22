"""P2.7 lifecycle: where Image QA sits between provider completion and human
selection, and what it does (and does not) block.

  provider completes → Image QA → provenance → recommendation → human selection

Real route + real orchestrator + real Higgsfield client over httpx.MockTransport;
the artifact fetcher is an in-memory fake, so no network and no provider call."""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.config import settings
from app.creative.artifact_fetcher import ArtifactFetchError
from app.creative.critic import select_direction
from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.dependencies import (
    get_creative_director,
    get_frontend_engineer,
    get_generated_artifact_fetcher,
    get_rate_limiter,
    get_session,
)
from app.domain.business_config.brand import BrandColors, BrandConfig, BrandTypography
from app.domain.creative.direction import CreativeConcept
from app.main import app
from app.security.rate_limit import InMemoryRateLimiter
from tests.test_creative_directions_composition_api import _business, _director, _Gateway, _logo, _post
from tests.test_creative_director import _brief, _direction


@pytest.fixture()
def client(session: Session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_rate_limiter] = lambda: InMemoryRateLimiter()
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_rate_limiter, None)
        app.dependency_overrides.pop(get_creative_director, None)


@pytest.fixture()
def cositas(session: Session, tenant: Tenant) -> Business:
    return _business(session, tenant, "cositas-y-puntos")


RESULT_URL = "https://d3example.cloudfront.net/out.png"  # what the mocked provider returns


def _png(size: tuple[int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (211, 205, 191)).save(buffer, "PNG")
    return buffer.getvalue()


GOOD = _png((480, 272))  # 16:9 within tolerance
BLOCKED = _png((480, 320))  # 3:2 — far outside the 16:9 contract


class Fetcher:
    def __init__(self, mapping: dict[str, bytes] | None = None, error: Exception | None = None) -> None:
        self.mapping, self.error, self.calls = mapping or {}, error, 0

    def fetch(self, url: str) -> bytes:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.mapping[url]


@pytest.fixture()
def use_fetcher():
    def install(fetcher: Fetcher) -> Fetcher:
        app.dependency_overrides[get_generated_artifact_fetcher] = lambda: fetcher
        return fetcher

    yield install
    app.dependency_overrides.pop(get_generated_artifact_fetcher, None)


def _generate(client: TestClient, session: Session, tenant: Tenant, business: Business, gateway=None):
    _logo(session, business)
    provider = gateway or _Gateway()
    app.dependency_overrides[get_creative_director] = lambda: _director(provider)
    return _post(client, business, tenant, {"hard_limit": 2.0})


def _spec(response) -> dict:
    return response.json()[0]["generation_metadata"]["creative_spec"]


def _generations(client: TestClient, business: Business, tenant: Tenant) -> list[dict]:
    return client.get(
        f"/businesses/{business.id}/creative-generations",
        headers={"X-Tenant-Id": str(tenant.id), "Origin": "http://localhost:5173"},
    ).json()


# --- the critic --------------------------------------------------------------------------------


def _blocked(direction):
    direction.generation_metadata = {
        "creative_spec": {"visual_qa": {"approval_eligible": False, "overall_status": "fail"}}
    }
    return direction


def test_a_qa_blocked_candidate_is_never_recommended_even_if_it_scores_higher():
    strong = _direction(
        concept=CreativeConcept(
            name="Cositas y Puntos handmade world",
            rationale="Grounded in Cositas y Puntos' handmade, artisanal crochet identity",
            narrative="A warm, handmade world for Cositas y Puntos",
        )
    )
    weak = _direction(concept=CreativeConcept(name="Modern Minimal", rationale="generic", narrative="n"))
    _blocked(strong)

    winner, candidates = select_direction([strong, weak], _brief())

    assert winner is weak and weak.is_recommended is True and strong.is_recommended is False
    assert "Visual QA" in strong.selection_rationale
    assert "cannot be turned into a website draft" in strong.selection_rationale
    assert candidates == [strong, weak]


def test_when_every_candidate_is_blocked_none_is_recommended():
    a, b = _blocked(_direction()), _blocked(_direction())

    winner, candidates = select_direction([a, b], _brief())

    assert winner is None and not any(c.is_recommended for c in candidates)
    assert all("Visual QA" in c.selection_rationale for c in candidates)


def test_warnings_and_missing_qa_never_affect_recommendation():
    warned = _direction()
    warned.generation_metadata = {
        "creative_spec": {"visual_qa": {"approval_eligible": True, "overall_status": "warning"}}
    }

    winner, _ = select_direction([warned, _direction()], _brief())

    assert winner is not None  # both remain eligible


# --- the route: pass / warning / block / not performed ------------------------------------------


def test_a_good_image_is_recorded_recommended_and_eligible(client, session, tenant, cositas, use_fetcher):
    use_fetcher(Fetcher({RESULT_URL: GOOD}))

    response = _generate(client, session, tenant, cositas)

    assert response.status_code == 201
    direction, spec = response.json()[0], _spec(response)
    qa = spec["visual_qa"]
    statuses = {c["name"]: c["status"] for c in qa["checks"]}
    assert qa["approval_eligible"] is True and qa["overall_status"] in {"pass", "warning"}
    assert direction["is_recommended"] is True
    assert statuses["image_integrity"] == "pass" and statuses["aspect_ratio"] == "pass"
    assert spec["validation"]["visual_qa"] == "performed" and len(spec["validation"]["not_covered"]) == 7
    assert RESULT_URL not in str(qa)  # QA provenance never carries the provider URL


def test_a_blocking_failure_blocks_recommendation_but_the_generation_stays_completed(
    client, session, tenant, cositas, use_fetcher
):
    use_fetcher(Fetcher({RESULT_URL: BLOCKED}))

    response = _generate(client, session, tenant, cositas)

    assert response.status_code == 201  # the provider job succeeded: this is NOT a provider failure
    direction, spec = response.json()[0], _spec(response)
    assert spec["visual_qa"]["approval_eligible"] is False and spec["visual_qa"]["overall_status"] == "fail"
    assert direction["is_recommended"] is False and "Visual QA" in direction["selection_rationale"]
    assert direction["provider_metadata"]["provider"] == "higgsfield" and direction["credits_used"] == 2.0
    row = _generations(client, cositas, tenant)[0]
    assert row["status"] == "completed" and row["error"] is None  # never provider_failed / failed
    assert spec["validation"]["status"] == "passed"  # the provider-side metadata verdict is untouched


def test_a_qa_blocked_direction_cannot_become_a_website_draft(client, session, tenant, cositas, use_fetcher):
    use_fetcher(Fetcher({RESULT_URL: BLOCKED}))
    direction_id = _generate(client, session, tenant, cositas).json()[0]["id"]
    app.dependency_overrides[get_frontend_engineer] = lambda: object()  # refused before the engine is ever used
    try:
        response = client.post(
            f"/businesses/{cositas.id}/website-drafts/generative",
            json={"creative_direction_id": direction_id},
            headers={"X-Tenant-Id": str(tenant.id), "Origin": "http://localhost:5173"},
        )
    finally:
        app.dependency_overrides.pop(get_frontend_engineer, None)

    assert response.status_code == 409 and response.json()["error"]["code"] == "visual_qa_blocked"


def test_a_corrupt_generated_file_is_a_blocking_integrity_failure(client, session, tenant, cositas, use_fetcher):
    use_fetcher(Fetcher({RESULT_URL: b"<html>the CDN returned an error page</html>"}))

    response = _generate(client, session, tenant, cositas)

    qa = _spec(response)["visual_qa"]
    assert qa["approval_eligible"] is False and qa["blocking_reasons"][0].startswith("image_integrity")
    assert response.json()[0]["is_recommended"] is False


def test_an_unretrievable_image_is_not_performed_and_never_blocks(client, session, tenant, cositas, use_fetcher):
    fetcher = use_fetcher(Fetcher(error=ArtifactFetchError("http_error")))  # e.g. an expired provider URL

    response = _generate(client, session, tenant, cositas)

    qa = _spec(response)["visual_qa"]
    assert fetcher.calls == 1
    assert qa["overall_status"] == "not_performed" and qa["approval_eligible"] is True
    assert all(c["status"] == "not_performed" for c in qa["checks"])
    assert response.json()[0]["is_recommended"] is True
    assert _spec(response)["validation"]["visual_qa"] == "not_performed"


def test_by_default_no_test_reaches_the_network_and_qa_is_not_performed(client, session, tenant, cositas):
    response = _generate(client, session, tenant, cositas)  # the autouse guard supplies a fetcher that fetches nothing

    qa = _spec(response)["visual_qa"]
    assert qa["overall_status"] == "not_performed" and qa["checks"][0]["evidence"] == {"fetch_error": "disabled"}


def test_a_palette_warning_is_visible_but_neither_blocks_nor_unrecommends(
    client, session, tenant, cositas, use_fetcher
):
    brand = BrandConfig(
        colors=BrandColors(
            primary="#E8735A", secondary="#C9A24A", accent="#7A1F3D", background="#FFFFFF", foreground="#111111"
        ),
        typography=BrandTypography(sans="Inter"),
    )
    cositas.config = {**cositas.config, "brand": brand.model_dump(mode="json")}
    session.flush()
    use_fetcher(Fetcher({RESULT_URL: GOOD}))  # a plain beige image: none of the requested colors appear

    response = _generate(client, session, tenant, cositas)

    spec = _spec(response)
    palette = next(c for c in spec["visual_qa"]["checks"] if c["name"] == "brand_palette_adherence")
    assert spec["scene_plan"]["brand_palette"] == ["#E8735A", "#C9A24A", "#7A1F3D"]
    assert palette["status"] == "warning" and palette["evidence"]["present_count"] == 0
    assert spec["visual_qa"]["approval_eligible"] is True and spec["visual_qa"]["warnings"]
    assert response.json()[0]["is_recommended"] is True


def test_the_kill_switch_restores_pre_p27_behavior(client, session, tenant, cositas, use_fetcher, monkeypatch):
    fetcher = use_fetcher(Fetcher({RESULT_URL: BLOCKED}))
    monkeypatch.setattr(settings, "visual_qa_enabled", False)

    response = _generate(client, session, tenant, cositas)

    assert "visual_qa" not in _spec(response) and fetcher.calls == 0
    assert response.json()[0]["is_recommended"] is True  # nothing was inspected, nothing is claimed
    assert _spec(response)["validation"]["visual_qa"] == "not_performed"


def test_an_internal_fallback_direction_has_no_image_so_no_qa_is_recorded_or_claimed(
    client, session, tenant, cositas, use_fetcher
):
    fetcher = use_fetcher(Fetcher({RESULT_URL: BLOCKED}))

    response = _generate(client, session, tenant, cositas, gateway=_Gateway(fail_with=(404, "model_not_found")))

    direction = response.json()[0]
    assert direction["provider_metadata"]["provider"] == "internal_fallback"
    assert "visual_qa" not in direction["generation_metadata"].get("creative_spec", {}) and fetcher.calls == 0
    assert direction["is_recommended"] is True
