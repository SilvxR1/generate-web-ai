"""POST /internal/leads, GET /internal/leads/{id}, POST
/internal/leads/{id}/follow-up-email, POST
/internal/leads/{id}/acknowledgement-email, and POST
/internal/notifications (app.routers.internal_automation): lead
persisted, wrong tenant/business rejected, missing/invalid token
rejected, notification handled, follow-up/acknowledgement email sent
through a fake NotificationSender, and the token never leaks into
logs."""

import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.models.business import Business
from app.db.models.internal_notification import InternalNotification
from app.db.models.lead import Lead
from app.db.models.tenant import Tenant
from app.dependencies import get_optional_notification_sender, get_session
from app.domain.enums import NotificationDeliveryStatus
from app.main import app
from app.notifications.errors import NotificationSenderError
from app.notifications.sender import NotificationEmail, NotificationSender

TOKEN = "test-internal-automation-token"


class _FakeNotificationSender(NotificationSender):
    """Test double standing in for a real email provider — no network,
    no real email ever sent. Injected via a dependency override, same
    pattern as the `client`/session override below."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[NotificationEmail] = []

    def send(self, message: NotificationEmail) -> None:
        if self.fail:
            raise NotificationSenderError("simulated provider failure")
        self.sent.append(message)


@pytest.fixture()
def notification_sender():
    sender = _FakeNotificationSender()
    app.dependency_overrides[get_optional_notification_sender] = lambda: sender
    try:
        yield sender
    finally:
        app.dependency_overrides.pop(get_optional_notification_sender, None)


BUSINESS_CONFIG_WITH_EMAIL_NOTIFICATIONS = {
    "schema_version": 1,
    "business_profile": {
        "name": "Reformas Valencia",
        "slug": "reformas-valencia",
        "industry": "home_renovation",
        "contact": {"email": "dueno@reformasvalencia.example"},
    },
    "communications": {"internal_notifications": {"email": True}},
}

# Distinct from the config above on purpose: customer_notifications is
# the customer-facing counterpart of internal_notifications, and a lead
# follow-up email must be gated by *this* flag, not that one.
BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS = {
    "schema_version": 1,
    "business_profile": {
        "name": "Reformas Valencia",
        "slug": "reformas-valencia",
        "industry": "home_renovation",
    },
    "communications": {"customer_notifications": {"email": True}},
}


@pytest.fixture()
def client(session):
    def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture(autouse=True)
def _configured_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "internal_automation_token", TOKEN)


def _lead_payload(tenant: Tenant, business: Business, **overrides: object) -> dict:
    payload = {
        "tenant_id": str(tenant.id),
        "business_id": str(business.id),
        "source": "website_form",
        "name": "Ana García",
        "email": "ana@example.com",
        "phone": "+34 600 00 00 00",
        "message": "Quiero un presupuesto para reformar la cocina.",
    }
    payload.update(overrides)
    return payload


# --- lead stored -------------------------------------------------------


def test_lead_stored_with_valid_token_and_known_business(client: TestClient, tenant: Tenant, business: Business):
    response = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Ana García"
    assert body["business_id"] == str(business.id)
    assert body["tenant_id"] == str(tenant.id)


def test_lead_response_includes_id_for_downstream_nodes(client: TestClient, tenant: Tenant, business: Business):
    response = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    )
    assert "id" in response.json()


# --- wrong tenant/business rejected -------------------------------------


def test_unknown_business_id_rejected(client: TestClient, tenant: Tenant):
    payload = {
        "tenant_id": str(tenant.id),
        "business_id": "00000000-0000-0000-0000-000000000000",
        "source": "website_form",
        "name": "Ana García",
    }
    response = client.post("/internal/leads", json=payload, headers={"X-Internal-Automation-Token": TOKEN})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_tenant_business"


def test_business_from_other_tenant_rejected(
    client: TestClient, tenant: Tenant, business: Business, other_tenant: Tenant
):
    # `business` really exists, but under `tenant` — presenting it
    # alongside `other_tenant`'s id must not validate, proving the
    # lookup is a real (tenant_id, business_id) pair check, not just
    # "does this business_id exist anywhere".
    payload = _lead_payload(other_tenant, business)
    response = client.post("/internal/leads", json=payload, headers={"X-Internal-Automation-Token": TOKEN})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_tenant_business"


# --- lead lookup (GET /internal/leads/{id}) --------------------------------


def _get_lead(client: TestClient, lead_id, tenant: Tenant, business: Business, **overrides: object):
    params = {"tenant_id": str(tenant.id), "business_id": str(business.id), **overrides}
    return client.get(f"/internal/leads/{lead_id}", params=params, headers={"X-Internal-Automation-Token": TOKEN})


def test_lead_lookup_returns_the_leads_current_status(client: TestClient, tenant: Tenant, business: Business):
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = _get_lead(client, lead_id, tenant, business)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == lead_id
    assert body["status"] == "new"
    assert body["name"] == "Ana García"


def test_lead_lookup_reflects_a_status_change_made_in_between(
    client: TestClient, session, tenant: Tenant, business: Business
):
    # The whole point of this endpoint: a caller that reads the lead
    # again later sees whatever it currently is, not a snapshot from
    # when it was first stored.
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]
    stored_lead = session.get(Lead, uuid.UUID(lead_id))
    stored_lead.status = "contacted"
    session.flush()

    response = _get_lead(client, lead_id, tenant, business)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "contacted"


def test_lead_lookup_for_unknown_lead_is_404(client: TestClient, tenant: Tenant, business: Business):
    response = _get_lead(client, uuid.uuid4(), tenant, business)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "lead_not_found"


def test_lead_lookup_rejects_wrong_tenant(client: TestClient, tenant: Tenant, business: Business, other_tenant: Tenant):
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = _get_lead(client, lead_id, other_tenant, business)

    assert response.status_code == 404


def test_lead_lookup_rejects_a_lead_from_a_different_business(
    client: TestClient, session, tenant: Tenant, business: Business
):
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]
    other_business = Business(
        tenant_id=tenant.id,
        name="Otra Empresa",
        slug="otra-empresa",
        vertical=business.vertical,
        raw_description="Otra empresa completamente distinta, sin relacion con la primera.",
        status=business.status,
    )
    session.add(other_business)
    session.flush()

    response = _get_lead(client, lead_id, tenant, other_business)

    assert response.status_code == 404


def test_lead_lookup_requires_tenant_and_business_query_params(client: TestClient, business: Business):
    response = client.get(f"/internal/leads/{uuid.uuid4()}", headers={"X-Internal-Automation-Token": TOKEN})

    assert response.status_code == 422


def test_lead_lookup_requires_a_valid_token(client: TestClient, tenant: Tenant, business: Business):
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = client.get(
        f"/internal/leads/{lead_id}", params={"tenant_id": str(tenant.id), "business_id": str(business.id)}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_internal_automation_token"


# --- lead follow-up email (POST /internal/leads/{id}/follow-up-email) -----


def _send_follow_up_email(client: TestClient, lead_id, tenant: Tenant, business: Business):
    return client.post(
        f"/internal/leads/{lead_id}/follow-up-email",
        json={"tenant_id": str(tenant.id), "business_id": str(business.id)},
        headers={"X-Internal-Automation-Token": TOKEN},
    )


def test_follow_up_email_sent_when_lead_is_new_and_customer_notifications_enabled(
    client: TestClient, session, tenant: Tenant, business: Business, notification_sender: _FakeNotificationSender
):
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = _send_follow_up_email(client, lead_id, tenant, business)

    assert response.status_code == 200, response.text
    assert response.json() == {"sent": True}
    assert len(notification_sender.sent) == 1
    assert notification_sender.sent[0].to == "ana@example.com"  # the lead's own email, never the business's


def test_follow_up_email_never_creates_an_internal_notification_row(
    client: TestClient, session, tenant: Tenant, business: Business, notification_sender: _FakeNotificationSender
):
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    _send_follow_up_email(client, lead_id, tenant, business)

    assert session.query(InternalNotification).filter_by(business_id=business.id).count() == 0


def test_follow_up_email_skipped_when_lead_has_no_email(
    client: TestClient, session, tenant: Tenant, business: Business, notification_sender: _FakeNotificationSender
):
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    lead_id = client.post(
        "/internal/leads",
        json=_lead_payload(tenant, business, email=None),
        headers={"X-Internal-Automation-Token": TOKEN},
    ).json()["id"]

    response = _send_follow_up_email(client, lead_id, tenant, business)

    assert response.status_code == 200, response.text
    assert response.json() == {"sent": False}
    assert notification_sender.sent == []


def test_follow_up_email_skipped_when_lead_is_no_longer_new(
    client: TestClient, session, tenant: Tenant, business: Business, notification_sender: _FakeNotificationSender
):
    # Re-checked here independently of whatever n8n's own condition
    # already established — this endpoint is authoritative, not a mirror.
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]
    stored_lead = session.get(Lead, uuid.UUID(lead_id))
    stored_lead.status = "contacted"
    session.flush()

    response = _send_follow_up_email(client, lead_id, tenant, business)

    assert response.status_code == 200, response.text
    assert response.json() == {"sent": False}
    assert notification_sender.sent == []


def test_follow_up_email_skipped_when_customer_notifications_disabled(
    client: TestClient, session, tenant: Tenant, business: Business, notification_sender: _FakeNotificationSender
):
    # business.config stays None (the shared fixture's default) — no
    # opt-in to customer-facing email, so nothing should be attempted
    # even though the lead is new and has a real email.
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = _send_follow_up_email(client, lead_id, tenant, business)

    assert response.status_code == 200, response.text
    assert response.json() == {"sent": False}
    assert notification_sender.sent == []


def test_follow_up_email_skipped_when_no_sender_configured(
    client: TestClient, session, tenant: Tenant, business: Business
):
    # No notification_sender fixture requested — conftest.py's autouse
    # _no_real_notification_sender_by_default fixture already makes
    # get_optional_notification_sender() -> None the default for every
    # test, regardless of what this environment's own .env has
    # configured (see the earlier email-infrastructure phase, and
    # tests/test_smtp_isolation.py for the regression coverage on that
    # guarantee itself), so nothing further needs to be forced here.
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = _send_follow_up_email(client, lead_id, tenant, business)

    assert response.status_code == 200, response.text
    assert response.json() == {"sent": False}


def test_follow_up_email_provider_failure_returns_502_and_fails_the_branch(
    client: TestClient, session, tenant: Tenant, business: Business
):
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    failing_sender = _FakeNotificationSender(fail=True)
    app.dependency_overrides[get_optional_notification_sender] = lambda: failing_sender
    try:
        lead_id = client.post(
            "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
        ).json()["id"]

        response = _send_follow_up_email(client, lead_id, tenant, business)

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "lead_follow_up_email_failed"
    finally:
        app.dependency_overrides.pop(get_optional_notification_sender, None)


def test_follow_up_email_for_unknown_lead_is_404(client: TestClient, tenant: Tenant, business: Business):
    response = _send_follow_up_email(client, uuid.uuid4(), tenant, business)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "lead_not_found"


def test_follow_up_email_rejects_wrong_tenant(
    client: TestClient, session, tenant: Tenant, business: Business, other_tenant: Tenant
):
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = _send_follow_up_email(client, lead_id, other_tenant, business)

    assert response.status_code == 404


def test_follow_up_email_rejects_a_lead_from_a_different_business(
    client: TestClient, session, tenant: Tenant, business: Business
):
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]
    other_business = Business(
        tenant_id=tenant.id,
        name="Otra Empresa",
        slug="otra-empresa",
        vertical=business.vertical,
        raw_description="Otra empresa completamente distinta, sin relacion con la primera.",
        status=business.status,
    )
    session.add(other_business)
    session.flush()

    response = _send_follow_up_email(client, lead_id, tenant, other_business)

    assert response.status_code == 404


def test_follow_up_email_requires_a_valid_token(client: TestClient, tenant: Tenant, business: Business):
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = client.post(
        f"/internal/leads/{lead_id}/follow-up-email",
        json={"tenant_id": str(tenant.id), "business_id": str(business.id)},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_internal_automation_token"


# --- lead acknowledgement email (POST /internal/leads/{id}/acknowledgement-email) --


def _send_acknowledgement_email(client: TestClient, lead_id, tenant: Tenant, business: Business):
    return client.post(
        f"/internal/leads/{lead_id}/acknowledgement-email",
        json={"tenant_id": str(tenant.id), "business_id": str(business.id)},
        headers={"X-Internal-Automation-Token": TOKEN},
    )


def test_acknowledgement_email_sent_when_customer_notifications_enabled(
    client: TestClient, session, tenant: Tenant, business: Business, notification_sender: _FakeNotificationSender
):
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = _send_acknowledgement_email(client, lead_id, tenant, business)

    assert response.status_code == 200, response.text
    assert response.json() == {"sent": True}
    assert len(notification_sender.sent) == 1
    sent = notification_sender.sent[0]
    assert sent.to == "ana@example.com"  # the lead's own email, never the business's
    assert sent.subject
    assert sent.body


def test_acknowledgement_email_never_creates_an_internal_notification_row(
    client: TestClient, session, tenant: Tenant, business: Business, notification_sender: _FakeNotificationSender
):
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    _send_acknowledgement_email(client, lead_id, tenant, business)

    assert session.query(InternalNotification).filter_by(business_id=business.id).count() == 0


def test_acknowledgement_email_skipped_when_lead_has_no_email(
    client: TestClient, session, tenant: Tenant, business: Business, notification_sender: _FakeNotificationSender
):
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    lead_id = client.post(
        "/internal/leads",
        json=_lead_payload(tenant, business, email=None),
        headers={"X-Internal-Automation-Token": TOKEN},
    ).json()["id"]

    response = _send_acknowledgement_email(client, lead_id, tenant, business)

    assert response.status_code == 200, response.text
    assert response.json() == {"sent": False}
    assert notification_sender.sent == []


def test_acknowledgement_email_sent_even_when_lead_is_no_longer_new(
    client: TestClient, session, tenant: Tenant, business: Business, notification_sender: _FakeNotificationSender
):
    # Unlike follow-up-email, acknowledgement isn't gated on the lead
    # still being NEW — it fires immediately off the just-stored lead,
    # so whatever happens to the lead afterwards doesn't change whether
    # "we got your message" was already true.
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]
    stored_lead = session.get(Lead, uuid.UUID(lead_id))
    stored_lead.status = "contacted"
    session.flush()

    response = _send_acknowledgement_email(client, lead_id, tenant, business)

    assert response.status_code == 200, response.text
    assert response.json() == {"sent": True}
    assert len(notification_sender.sent) == 1


def test_acknowledgement_email_skipped_when_customer_notifications_disabled(
    client: TestClient, session, tenant: Tenant, business: Business, notification_sender: _FakeNotificationSender
):
    # business.config stays None (the shared fixture's default) — no
    # opt-in to customer-facing email, so nothing should be attempted
    # even though the lead is new and has a real email.
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = _send_acknowledgement_email(client, lead_id, tenant, business)

    assert response.status_code == 200, response.text
    assert response.json() == {"sent": False}
    assert notification_sender.sent == []


def test_acknowledgement_email_skipped_when_no_sender_configured(
    client: TestClient, session, tenant: Tenant, business: Business
):
    # No notification_sender fixture requested — conftest.py's autouse
    # _no_real_notification_sender_by_default fixture already makes
    # get_optional_notification_sender() -> None the default for every
    # test, regardless of what this environment's own .env has
    # configured.
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = _send_acknowledgement_email(client, lead_id, tenant, business)

    assert response.status_code == 200, response.text
    assert response.json() == {"sent": False}


def test_acknowledgement_email_provider_failure_returns_502_and_fails_the_branch(
    client: TestClient, session, tenant: Tenant, business: Business
):
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    failing_sender = _FakeNotificationSender(fail=True)
    app.dependency_overrides[get_optional_notification_sender] = lambda: failing_sender
    try:
        lead_id = client.post(
            "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
        ).json()["id"]

        response = _send_acknowledgement_email(client, lead_id, tenant, business)

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "lead_acknowledgement_email_failed"
    finally:
        app.dependency_overrides.pop(get_optional_notification_sender, None)


def test_acknowledgement_email_for_unknown_lead_is_404(client: TestClient, tenant: Tenant, business: Business):
    response = _send_acknowledgement_email(client, uuid.uuid4(), tenant, business)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "lead_not_found"


def test_acknowledgement_email_rejects_wrong_tenant(
    client: TestClient, session, tenant: Tenant, business: Business, other_tenant: Tenant
):
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = _send_acknowledgement_email(client, lead_id, other_tenant, business)

    assert response.status_code == 404


def test_acknowledgement_email_rejects_a_lead_from_a_different_business(
    client: TestClient, session, tenant: Tenant, business: Business
):
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]
    other_business = Business(
        tenant_id=tenant.id,
        name="Otra Empresa",
        slug="otra-empresa",
        vertical=business.vertical,
        raw_description="Otra empresa completamente distinta, sin relacion con la primera.",
        status=business.status,
    )
    session.add(other_business)
    session.flush()

    response = _send_acknowledgement_email(client, lead_id, tenant, other_business)

    assert response.status_code == 404


def test_acknowledgement_email_requires_a_valid_token(client: TestClient, tenant: Tenant, business: Business):
    lead_id = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    ).json()["id"]

    response = client.post(
        f"/internal/leads/{lead_id}/acknowledgement-email",
        json={"tenant_id": str(tenant.id), "business_id": str(business.id)},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_internal_automation_token"


# --- missing/invalid token rejected --------------------------------------


def test_missing_token_rejected(client: TestClient, tenant: Tenant, business: Business):
    response = client.post("/internal/leads", json=_lead_payload(tenant, business))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_internal_automation_token"


def test_invalid_token_rejected(client: TestClient, tenant: Tenant, business: Business):
    response = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": "wrong-token"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_internal_automation_token"


def test_unconfigured_token_rejects_everything(
    client: TestClient, tenant: Tenant, business: Business, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "internal_automation_token", None)

    response = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "internal_automation_not_configured"


# --- notification handled ------------------------------------------------


def test_notification_handled_and_recorded_but_not_marked_delivered(
    client: TestClient, tenant: Tenant, business: Business
):
    lead_response = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    )
    lead = lead_response.json()

    response = client.post("/internal/notifications", json=lead, headers={"X-Internal-Automation-Token": TOKEN})

    assert response.status_code == 201, response.text
    body = response.json()
    # No NotificationSender configured for this test (no `notification_sender`
    # fixture used) — a legitimate "not set up yet" no-op, never simulated
    # as sent. See the "notification delivered" tests below for the real
    # delivery path against a fake provider.
    assert body["delivered"] is False
    assert body["channel"] == "internal"
    assert "Ana García" in body["summary"]


def test_notification_rejects_unknown_business(client: TestClient, tenant: Tenant):
    payload = {
        "tenant_id": str(tenant.id),
        "business_id": "00000000-0000-0000-0000-000000000000",
        "source": "website_form",
    }
    response = client.post("/internal/notifications", json=payload, headers={"X-Internal-Automation-Token": TOKEN})

    assert response.status_code == 404


# --- notification delivered (real send attempt, fake provider) -----------


def test_notification_delivered_via_email_marks_delivered_true(
    client: TestClient, session, tenant: Tenant, business: Business, notification_sender: _FakeNotificationSender
):
    business.config = BUSINESS_CONFIG_WITH_EMAIL_NOTIFICATIONS
    session.flush()
    lead_response = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    )
    lead = lead_response.json()

    response = client.post("/internal/notifications", json=lead, headers={"X-Internal-Automation-Token": TOKEN})

    assert response.status_code == 201, response.text
    assert response.json()["delivered"] is True
    assert len(notification_sender.sent) == 1
    sent = notification_sender.sent[0]
    assert sent.to == "dueno@reformasvalencia.example"  # the business's own contact email, never the lead's
    assert "Reformas Valencia" in sent.subject


def test_business_without_email_notifications_enabled_is_not_delivered(
    client: TestClient, session, tenant: Tenant, business: Business, notification_sender: _FakeNotificationSender
):
    # business.config stays None (the shared fixture's default) — no
    # opt-in to email notifications, so nothing should be attempted.
    lead_response = client.post(
        "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
    )
    lead = lead_response.json()

    response = client.post("/internal/notifications", json=lead, headers={"X-Internal-Automation-Token": TOKEN})

    assert response.status_code == 201, response.text
    assert response.json()["delivered"] is False
    assert notification_sender.sent == []


def test_provider_failure_returns_502_but_keeps_the_notification_persisted_as_undelivered(
    client: TestClient, session, tenant: Tenant, business: Business
):
    business.config = BUSINESS_CONFIG_WITH_EMAIL_NOTIFICATIONS
    session.flush()
    failing_sender = _FakeNotificationSender(fail=True)
    app.dependency_overrides[get_optional_notification_sender] = lambda: failing_sender
    try:
        lead_response = client.post(
            "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
        )
        lead = lead_response.json()

        response = client.post("/internal/notifications", json=lead, headers={"X-Internal-Automation-Token": TOKEN})

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "notification_delivery_failed"

        # The notification row must survive this request failing — see
        # app.routers.internal_automation.ingest_notification's own
        # comment on why it commits before attempting delivery.
        notifications = session.query(InternalNotification).filter_by(business_id=business.id).all()
        assert len(notifications) == 1
        assert notifications[0].delivered is False
        # Regression: status must be persisted as FAILED, not left at its
        # PENDING default — a naive `except: raise` here would let
        # get_session's rollback-on-exception silently discard the
        # in-memory FAILED mutation, since it was never flushed after the
        # earlier successful commit.
        assert notifications[0].status is NotificationDeliveryStatus.FAILED
    finally:
        app.dependency_overrides.pop(get_optional_notification_sender, None)


def test_acknowledgement_email_provider_failure_persists_failed_status(
    client: TestClient, session, tenant: Tenant, business: Business
):
    business.config = BUSINESS_CONFIG_WITH_CUSTOMER_EMAIL_NOTIFICATIONS
    session.flush()
    failing_sender = _FakeNotificationSender(fail=True)
    app.dependency_overrides[get_optional_notification_sender] = lambda: failing_sender
    try:
        lead_id = client.post(
            "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
        ).json()["id"]

        response = _send_acknowledgement_email(client, lead_id, tenant, business)
        assert response.status_code == 502

        # Same regression as the internal-notification case above: the
        # FAILED mutation must survive this request's own rollback.
        lead = session.query(Lead).filter_by(id=uuid.UUID(lead_id)).one()
        assert lead.acknowledgement_status is NotificationDeliveryStatus.FAILED
    finally:
        app.dependency_overrides.pop(get_optional_notification_sender, None)


def test_lead_survives_a_failed_notification_delivery(client: TestClient, session, tenant: Tenant, business: Business):
    business.config = BUSINESS_CONFIG_WITH_EMAIL_NOTIFICATIONS
    session.flush()
    failing_sender = _FakeNotificationSender(fail=True)
    app.dependency_overrides[get_optional_notification_sender] = lambda: failing_sender
    try:
        lead_response = client.post(
            "/internal/leads", json=_lead_payload(tenant, business), headers={"X-Internal-Automation-Token": TOKEN}
        )
        assert lead_response.status_code == 201
        lead_id = lead_response.json()["id"]

        client.post(
            "/internal/notifications", json=lead_response.json(), headers={"X-Internal-Automation-Token": TOKEN}
        )

        stored_lead = session.get(Lead, uuid.UUID(lead_id))
        assert stored_lead is not None
        assert stored_lead.name == "Ana García"
    finally:
        app.dependency_overrides.pop(get_optional_notification_sender, None)


# --- secrets never logged -------------------------------------------------


def test_invalid_token_value_never_appears_in_logs(
    client: TestClient, tenant: Tenant, business: Business, caplog: pytest.LogCaptureFixture
):
    secret_looking_token = "wrong-but-secret-shaped-abc123"
    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/internal/leads",
            json=_lead_payload(tenant, business),
            headers={"X-Internal-Automation-Token": secret_looking_token},
        )

    assert response.status_code == 401
    all_log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_looking_token not in all_log_text
    assert TOKEN not in all_log_text
