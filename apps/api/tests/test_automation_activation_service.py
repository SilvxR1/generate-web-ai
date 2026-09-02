"""activate/deactivate_lead_capture_automation (app.automation.activation)
against a mocked n8n API (httpx.MockTransport, same pattern as
test_n8n_engine.py) and a real (sqlite, in-memory) session — success,
persistence of the Workflow row, idempotent repeated activation,
deactivate/reactivate, missing/unsupported capability configuration,
automation not enabled, engine failure never marking anything active or
mutating what was already persisted, tenant isolation, and that the n8n
API key never appears in the result or in any request body."""

import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.automation.activation import (
    AutomationActivationError,
    activate_lead_capture_automation,
    deactivate_lead_capture_automation,
    get_automation_state,
)
from app.automation.n8n import N8nClient
from app.config import Settings
from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.db.models.workflow import Workflow
from app.domain.business_config import EXAMPLE_REFORMA_VALENCIA_CONFIG
from app.domain.enums import WorkflowStatus
from app.repositories.workflow import WorkflowRepository

API_KEY = "n8n-super-secret-api-key"


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "internal_api_base_url": "http://localhost:8000",
        "n8n_base_url": "https://n8n.example.com",
        "n8n_api_key": API_KEY,
        "n8n_email_credential_id": "n8n-smtp-credential-id",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _client(handler) -> N8nClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://n8n.example.com")
    return N8nClient("https://n8n.example.com", API_KEY, http_client=http_client)


def _activate(handler, session: Session, business: Business, **overrides: object):
    return activate_lead_capture_automation(
        session=session,
        business_config=EXAMPLE_REFORMA_VALENCIA_CONFIG,
        tenant_id=business.tenant_id,
        business_id=business.id,
        settings=_settings(**overrides),
        client=_client(handler),
    )


def _deactivate(handler, session: Session, business: Business, **overrides: object):
    return deactivate_lead_capture_automation(
        session=session,
        tenant_id=business.tenant_id,
        business_id=business.id,
        settings=_settings(**overrides),
        client=_client(handler),
    )


def _create_and_activate_handler(workflow_name: str = "wf"):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(201, json={"id": "42", "name": workflow_name, "active": False})
        if request.url.path == "/api/v1/workflows/42/activate":
            return httpx.Response(200, json={"id": "42", "name": workflow_name, "active": True})
        raise AssertionError(f"unexpected request to {request.url.path}")

    return handler


# --- success / persistence ---------------------------------------------------


def test_first_activation_persists_a_workflow_row(session: Session, business: Business):
    workflow_name = "Reforma Casa Valencia — Lead capture"
    result = _activate(_create_and_activate_handler(workflow_name), session, business)

    assert result.remote_id == "42"
    assert result.active is True
    assert result.status is WorkflowStatus.ACTIVE
    assert result.workflow_id == "reforma-casa-valencia-lead-capture"
    assert set(result.required_capabilities) == {
        "lead.store",
        "lead.lookup",
        "lead.follow_up_email",
        "notification.send",
        "email.send",
        "wait",
    }
    assert result.activated_at is not None

    row = WorkflowRepository(session).get_for_business(business.tenant_id, business.id)
    assert row is not None
    assert row.n8n_workflow_id == "42"
    assert row.status is WorkflowStatus.ACTIVE
    assert row.local_workflow_id == "reforma-casa-valencia-lead-capture"
    assert row.version == 1
    assert row.name == workflow_name


def test_activation_never_leaks_the_n8n_api_key(session: Session, business: Business):
    def handler(request: httpx.Request) -> httpx.Response:
        assert API_KEY not in request.url.__str__()
        assert API_KEY not in (request.content.decode() if request.content else "")
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(201, json={"id": "42", "name": "wf", "active": False})
        return httpx.Response(200, json={"id": "42", "name": "wf", "active": True})

    result = _activate(handler, session, business)

    dumped = json.dumps(result.model_dump(mode="json"))
    assert API_KEY not in dumped
    assert API_KEY not in repr(result)


# --- idempotent repeated activation ------------------------------------------


def test_repeated_activation_does_not_duplicate_or_call_n8n_again(session: Session, business: Business):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(201, json={"id": "42", "name": "wf", "active": False})
        return httpx.Response(200, json={"id": "42", "name": "wf", "active": True})

    first = _activate(handler, session, business)

    def must_not_be_called(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call n8n again when already active")

    second = activate_lead_capture_automation(
        session=session,
        business_config=EXAMPLE_REFORMA_VALENCIA_CONFIG,
        tenant_id=business.tenant_id,
        business_id=business.id,
        settings=_settings(),
        client=_client(must_not_be_called),
    )

    assert len(calls) == 2  # create + activate, exactly once
    assert second.remote_id == first.remote_id
    assert second.status is WorkflowStatus.ACTIVE

    rows = session.scalars(select(Workflow)).all()
    assert len(rows) == 1


# --- deactivate ---------------------------------------------------------------


def test_deactivate_success_flips_status_to_inactive(session: Session, business: Business):
    _activate(_create_and_activate_handler(), session, business)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/workflows/42/deactivate"
        return httpx.Response(200, json={"id": "42", "name": "wf", "active": False})

    result = _deactivate(handler, session, business)

    assert result.status is WorkflowStatus.INACTIVE
    assert result.active is False
    assert result.remote_id == "42"


def test_deactivate_remote_failure_keeps_local_state_unchanged(session: Session, business: Business):
    activated = _activate(_create_and_activate_handler(), session, business)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    with pytest.raises(AutomationActivationError) as exc_info:
        _deactivate(handler, session, business)

    assert exc_info.value.code == "automation_deactivation_failed"

    state = get_automation_state(session=session, tenant_id=business.tenant_id, business_id=business.id)
    assert state is not None
    assert state.status is WorkflowStatus.ACTIVE
    assert state.remote_id == activated.remote_id


def test_deactivate_without_prior_activation_is_rejected(session: Session, business: Business):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call n8n when nothing was ever activated")

    with pytest.raises(AutomationActivationError) as exc_info:
        _deactivate(handler, session, business)

    assert exc_info.value.code == "automation_not_activated"
    assert exc_info.value.status_code == 404


# --- reactivate ----------------------------------------------------------------


def test_reactivate_after_deactivate_pushes_current_definition_and_activates(
    session: Session, business: Business
):
    _activate(_create_and_activate_handler(), session, business)
    _deactivate(lambda r: httpx.Response(200, json={"id": "42", "name": "wf", "active": False}), session, business)

    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "PUT" and request.url.path == "/api/v1/workflows/42":
            return httpx.Response(200, json={"id": "42", "name": "wf", "active": False})
        if request.url.path == "/api/v1/workflows/42/activate":
            return httpx.Response(200, json={"id": "42", "name": "wf", "active": True})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    result = activate_lead_capture_automation(
        session=session,
        business_config=EXAMPLE_REFORMA_VALENCIA_CONFIG,
        tenant_id=business.tenant_id,
        business_id=business.id,
        settings=_settings(),
        client=_client(handler),
    )

    assert result.status is WorkflowStatus.ACTIVE
    assert result.remote_id == "42"
    assert ("PUT", "/api/v1/workflows/42") in calls
    assert ("POST", "/api/v1/workflows/42/activate") in calls
    # never re-creates — no POST to the collection endpoint
    assert ("POST", "/api/v1/workflows") not in calls


# --- reload returns persisted state -------------------------------------------


def test_get_automation_state_returns_none_before_any_activation(session: Session, business: Business):
    assert get_automation_state(session=session, tenant_id=business.tenant_id, business_id=business.id) is None


def test_get_automation_state_reflects_persisted_state_after_reload(session: Session, business: Business):
    activated = _activate(_create_and_activate_handler(), session, business)

    reloaded = get_automation_state(session=session, tenant_id=business.tenant_id, business_id=business.id)

    assert reloaded is not None
    assert reloaded.remote_id == activated.remote_id
    assert reloaded.status is WorkflowStatus.ACTIVE
    assert reloaded.workflow_id == activated.workflow_id


# --- tenant isolation ----------------------------------------------------------


def test_tenant_isolation_workflow_not_visible_to_another_tenant(
    session: Session, business: Business, other_tenant: Tenant
):
    _activate(_create_and_activate_handler(), session, business)

    state = get_automation_state(session=session, tenant_id=other_tenant.id, business_id=business.id)

    assert state is None


# --- automation not enabled --------------------------------------------------


def test_automation_not_enabled_is_rejected_before_touching_n8n(session: Session, business: Business):
    disabled = EXAMPLE_REFORMA_VALENCIA_CONFIG.model_copy(deep=True)
    disabled.automation.lead_capture = False

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call n8n when lead_capture is disabled")

    with pytest.raises(AutomationActivationError) as exc_info:
        activate_lead_capture_automation(
            session=session,
            business_config=disabled,
            tenant_id=business.tenant_id,
            business_id=business.id,
            settings=_settings(),
            client=_client(handler),
        )

    assert exc_info.value.code == "automation_not_enabled"
    assert exc_info.value.status_code == 409


# --- missing capability configuration ----------------------------------------


def test_missing_email_credential_is_rejected_before_touching_n8n(session: Session, business: Business):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call n8n when a required capability isn't configured")

    with pytest.raises(AutomationActivationError) as exc_info:
        _activate(handler, session, business, n8n_email_credential_id=None)

    assert exc_info.value.code == "missing_capability_configuration"
    assert exc_info.value.status_code == 409


# --- failure never marks anything active / never persists ---------------------


def test_n8n_failure_during_create_is_reported_and_nothing_is_persisted(session: Session, business: Business):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    with pytest.raises(AutomationActivationError) as exc_info:
        _activate(handler, session, business)

    assert exc_info.value.code == "automation_activation_failed"
    assert get_automation_state(session=session, tenant_id=business.tenant_id, business_id=business.id) is None


def test_n8n_failure_during_the_activate_step_is_reported_after_a_successful_create(
    session: Session, business: Business
):
    """Create succeeds (n8n now has the workflow, inactive) but the
    activate call itself fails — must surface as a failure, never as a
    result claiming `active`, and never persist anything."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/workflows":
            return httpx.Response(201, json={"id": "42", "name": "wf", "active": False})
        return httpx.Response(503, text="n8n unavailable")

    with pytest.raises(AutomationActivationError) as exc_info:
        _activate(handler, session, business)

    assert exc_info.value.code == "automation_activation_failed"
    assert get_automation_state(session=session, tenant_id=business.tenant_id, business_id=business.id) is None
