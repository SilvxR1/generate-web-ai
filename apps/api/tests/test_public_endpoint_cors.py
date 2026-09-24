"""A8.3.4-P0 — PublicEndpointCORSMiddleware: customer websites (any origin:
their *.pages.dev project or custom domain) can POST to the two anonymous
public endpoints with NON-credentialed CORS, while every authenticated
Studio route keeps the strict, credentialed CORS_ORIGINS policy."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app

BUSINESS = str(uuid.uuid4())
CUSTOMER_ORIGINS = ["https://cositasypuntos.com", "https://site-0123456789abcdef.pages.dev"]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _preflight(client: TestClient, path: str, origin: str, method: str = "POST"):
    return client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type",
        },
    )


@pytest.mark.parametrize("endpoint", ["leads", "events"])
@pytest.mark.parametrize("origin", CUSTOMER_ORIGINS)
def test_customer_site_preflight_is_allowed_without_credentials(client, endpoint, origin):
    response = _preflight(client, f"/public/businesses/{BUSINESS}/{endpoint}", origin)

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == "*"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize("endpoint", ["leads", "events"])
def test_actual_public_response_carries_non_credentialed_cors(client, endpoint):
    # An invalid body: the route answers 422 without creating anything, but
    # the browser must still be able to read the response.
    response = client.post(
        f"/public/businesses/{BUSINESS}/{endpoint}", json={}, headers={"Origin": CUSTOMER_ORIGINS[0]}
    )

    assert response.status_code in (400, 404, 422)
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers


def test_authenticated_studio_cors_is_unchanged(client):
    studio = settings.cors_origins[0]

    allowed = _preflight(client, "/auth/me", studio, method="GET")
    assert allowed.headers["access-control-allow-origin"] == studio
    assert allowed.headers["access-control-allow-credentials"] == "true"

    denied = _preflight(client, "/auth/me", CUSTOMER_ORIGINS[0], method="GET")
    assert "access-control-allow-origin" not in denied.headers


def test_only_the_two_browser_endpoints_are_opened(client):
    for path in (f"/public/businesses/{BUSINESS}", f"/public/businesses/{BUSINESS}/leads/extra", "/businesses"):
        response = _preflight(client, path, CUSTOMER_ORIGINS[0])
        assert response.headers.get("access-control-allow-origin") != "*"
