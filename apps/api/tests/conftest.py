import smtplib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401 — registers every model on Base.metadata
from app.db.base import Base
from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.dependencies import get_optional_notification_sender
from app.domain.enums import BusinessStatus, BusinessVertical
from app.main import app


class RealSmtpConnectionBlocked(AssertionError):
    """Raised by the session-wide smtplib.SMTP guard below whenever
    something tries to open a real SMTP connection during this test
    suite — a subclass of AssertionError (a test-hygiene failure, not a
    delivery outcome) and deliberately *not* a subclass of
    smtplib.SMTPException or OSError, so SmtpNotificationSender.send()'s
    own `except (smtplib.SMTPException, OSError)` never catches and
    silently turns it into a NotificationSenderError — it always
    propagates straight up as a hard test failure.
    """


def _blocked_smtp(*args: object, **kwargs: object) -> None:
    raise RealSmtpConnectionBlocked(
        "A test tried to open a real smtplib.SMTP connection. apps/api/.env can carry real "
        "SMTP credentials (see the email-infrastructure phase) — tests must never reach the "
        "real network regardless. Either let the default get_optional_notification_sender "
        "override below apply (nothing to do), override it yourself with a fake sender (see "
        "test_internal_automation_api.py's notification_sender fixture), or, if you're "
        "specifically testing SmtpNotificationSender itself, mock smtplib.SMTP directly the "
        "way test_notification_sender_smtp.py does."
    )


@pytest.fixture(autouse=True, scope="session")
def _block_real_smtp_connections_for_the_whole_suite():
    """The last-resort net, active for every test with no per-test setup:
    even if something bypasses the dependency-override fixture below —
    a future code path that constructs SmtpNotificationSender directly,
    or a test that clears the override without restoring it — actually
    constructing smtplib.SMTP raises immediately instead of opening a
    socket.

    Tests that deliberately exercise SmtpNotificationSender's real
    behavior (test_notification_sender_smtp.py) use their own
    `monkeypatch.setattr(smtplib, "SMTP", ...)`, a *separate*
    pytest.MonkeyPatch instance that records "before = this guard" and
    restores exactly that on teardown — so their local patch shadows
    this one for its own test, then reverts back to this guard
    afterward, never to the real smtplib.SMTP.
    """
    guard = pytest.MonkeyPatch()
    guard.setattr(smtplib, "SMTP", _blocked_smtp)
    yield
    guard.undo()


@pytest.fixture(autouse=True)
def _no_real_notification_sender_by_default():
    """The primary isolation point (preferred over the smtplib guard
    above, which exists only as a backstop): every test gets
    get_optional_notification_sender() -> None by default on the real
    FastAPI app, regardless of what apps/api/.env actually has
    configured — the same "SMTP not set up yet" behavior a real caller
    sees with no credentials configured, applied uniformly during tests
    so a test's outcome never depends on which credentials happen to be
    sitting in .env at the time.

    A test that wants a real send *attempt* (against a fake provider,
    never smtplib for real) overrides this same dependency again in its
    own fixture — see test_internal_automation_api.py's
    notification_sender fixture. Because autouse fixtures set up before
    explicitly-requested ones (pytest's own ordering rule) and tear down
    in the reverse order, that test-specific override cleanly replaces
    this default during the test body and is popped first at teardown,
    with no coordination needed between the two fixtures.

    Only ever touches `app.dependency_overrides` (a test-only dict on
    the FastAPI app object) — production and a real `uvicorn` process
    never go through this module at all, so real usage is unaffected.
    """
    app.dependency_overrides[get_optional_notification_sender] = lambda: None
    yield
    app.dependency_overrides.pop(get_optional_notification_sender, None)


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine) -> Session:
    factory: sessionmaker[Session] = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db_session = factory()
    try:
        yield db_session
    finally:
        db_session.close()


@pytest.fixture()
def tenant(session: Session) -> Tenant:
    t = Tenant(name="Acme Studio")
    session.add(t)
    session.flush()
    return t


@pytest.fixture()
def other_tenant(session: Session) -> Tenant:
    t = Tenant(name="Other Agency")
    session.add(t)
    session.flush()
    return t


@pytest.fixture()
def business(session: Session, tenant: Tenant) -> Business:
    b = Business(
        tenant_id=tenant.id,
        name="Reformas Valencia",
        slug="reformas-valencia",
        vertical=BusinessVertical.HOME_RENOVATION,
        raw_description="Empresa de reformas integrales en Valencia con mas de 10 anos de experiencia.",
        status=BusinessStatus.DRAFT,
    )
    session.add(b)
    session.flush()
    return b
