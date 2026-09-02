"""Exercises app.errors.register_exception_handlers in isolation, on a
throwaway FastAPI app, so these stay unit tests of the error-handling
behavior itself rather than depending on any real production route."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.errors import AppError, register_exception_handlers


class _Payload(BaseModel):
    name: str


def _build_test_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom-app-error")
    def boom_app_error():
        raise AppError("business rule violated", code="business_rule_violation", status_code=409)

    @app.get("/boom-unexpected")
    def boom_unexpected():
        raise RuntimeError("something broke internally")

    @app.post("/validate")
    def validate(payload: _Payload):
        return {"name": payload.name}

    return app


def test_app_error_returns_structured_response():
    client = TestClient(_build_test_app())

    response = client.get("/boom-app-error")

    assert response.status_code == 409
    assert response.json() == {"error": {"code": "business_rule_violation", "message": "business rule violated"}}


def test_unhandled_exception_returns_structured_500_without_leaking_internals():
    client = TestClient(_build_test_app(), raise_server_exceptions=False)

    response = client.get("/boom-unexpected")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "something broke internally" not in body["error"]["message"]


def test_validation_error_returns_structured_response_with_details():
    client = TestClient(_build_test_app())

    response = client.post("/validate", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert isinstance(body["error"]["details"], list)


def test_not_found_returns_structured_http_error():
    client = TestClient(_build_test_app())

    response = client.get("/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "http_error"
