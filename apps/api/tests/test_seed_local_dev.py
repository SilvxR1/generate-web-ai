"""DEV-3: scripts/seed_local_dev.py refuses anything but a fresh local
development PostgreSQL, never touches a tenant that is not its own, and is
idempotent. The seed logic runs on the suite's in-memory SQLite session; the
entry point is exercised with make_engine replaced, so no test ever connects
to a database server.
"""

import importlib.util
import os
import uuid

import pytest
from sqlalchemy import func, select

from app.db.models.business import Business
from app.db.models.tenant import Tenant
from app.db.models.tenant_access import TenantAccess
from app.db.models.user import User
from app.security.passwords import hash_password, verify_password
from tests.isolation import API_ROOT

_spec = importlib.util.spec_from_file_location("seed_local_dev", os.path.join(API_ROOT, "scripts", "seed_local_dev.py"))
seed_local_dev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_local_dev)
SeedRefused = seed_local_dev.SeedRefused

LOCAL_URL = "postgresql+psycopg://generate_web_ai:generate_web_ai@localhost:5432/generate_web_ai"
FAKE_PASSWORD = "dev3-fake-password-never-printed"
COSITAS_BUSINESS_ID = uuid.UUID("884eb764-2449-4bbe-a644-9d8d937f7a9d")


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


class _Passwords:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return "local-dev-password"


# --- Target checks (before any connection) ----------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        LOCAL_URL,
        "postgresql://generate_web_ai:generate_web_ai@127.0.0.1:5432/generate_web_ai",
        "postgresql+psycopg://generate_web_ai:generate_web_ai@[::1]:5432/generate_web_ai",
    ],
)
def test_a_local_development_postgres_is_accepted(url):
    seed_local_dev.check_target("development", url)


@pytest.mark.parametrize("environment", ["production", "staging", "test", "Development", ""])
def test_any_environment_but_development_is_refused(environment):
    with pytest.raises(SeedRefused, match="ENVIRONMENT"):
        seed_local_dev.check_target(environment, LOCAL_URL)


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        (f"postgresql+psycopg://user:{FAKE_PASSWORD}@db.example.invalid:5432/app", "loopback"),
        (f"postgresql+psycopg://user:{FAKE_PASSWORD}@10.0.0.5:5432/app", "loopback"),
        (f"postgresql+psycopg://user:{FAKE_PASSWORD}@postgres:5432/app", "loopback"),  # compose-only name
        (f"postgresql+psycopg://user:{FAKE_PASSWORD}@/app", "loopback"),  # Unix socket / default host
        ("sqlite:///./dev.db", "PostgreSQL"),
        ("sqlite://", "PostgreSQL"),
        (f"mysql://user:{FAKE_PASSWORD}@localhost/app", "PostgreSQL"),
        (f"postgresql://postgres:{FAKE_PASSWORD}@localhost:5432/railway", "production"),
        (f"postgresql://prod_admin:{FAKE_PASSWORD}@localhost:5432/app", "production"),
        (f"postgresql://user:{FAKE_PASSWORD}@localhost:5432/gwa_production", "production"),
        (f"postgresql://user:{FAKE_PASSWORD}@localhost:5432/cositas", "production"),
        ("not a url", "parsed"),
    ],
)
def test_unsafe_database_targets_are_refused_without_echoing_them(url, reason):
    with pytest.raises(SeedRefused, match=reason) as refused:
        seed_local_dev.check_target("development", url)

    message = str(refused.value)
    assert FAKE_PASSWORD not in message and "example.invalid" not in message and "10.0.0.5" not in message


# --- Entry point: refusals happen before connecting -------------------------------------------------


@pytest.fixture()
def no_connection(monkeypatch):
    import app.db.session

    def _refuse(*args, **kwargs):
        raise AssertionError("the seed must not create an engine for an unsafe target")

    monkeypatch.setattr(app.db.session, "make_engine", _refuse)


@pytest.mark.parametrize(
    ("argv", "environment", "database_url", "expected"),
    [
        ([], "development", LOCAL_URL, "--confirm-local-seed"),
        (["--confirm-local-seed"], "production", LOCAL_URL, "ENVIRONMENT"),
        (
            ["--confirm-local-seed"],
            "development",
            f"postgresql+psycopg://user:{FAKE_PASSWORD}@prod-db.example.invalid:5432/app",
            "loopback",
        ),
        (["--confirm-local-seed"], "development", "sqlite://", "PostgreSQL"),
    ],
)
def test_main_refuses_before_connecting(no_connection, monkeypatch, capsys, argv, environment, database_url, expected):
    from app.config import settings

    monkeypatch.setattr(settings, "environment", environment)
    monkeypatch.setattr(settings, "database_url", database_url)

    assert seed_local_dev.main(argv) == 1

    captured = capsys.readouterr()
    assert "REFUSING" in captured.err and expected in captured.err and "Nothing written" in captured.err
    assert FAKE_PASSWORD not in captured.out + captured.err
    assert "example.invalid" not in captured.out + captured.err


# --- Seed logic --------------------------------------------------------------------------------------


def test_the_seed_creates_one_fictional_tenant_business_and_owner(session):
    result = seed_local_dev.seed(session, password_provider=lambda: FAKE_PASSWORD)

    assert result == seed_local_dev.SeedResult(True, True, True, True)
    tenant = session.get(Tenant, seed_local_dev.TENANT_ID)
    business = session.get(Business, seed_local_dev.BUSINESS_ID)
    user = session.scalars(select(User)).one()
    access = session.scalars(select(TenantAccess)).one()
    assert tenant.name == seed_local_dev.TENANT_NAME
    assert business.tenant_id == tenant.id and business.slug == seed_local_dev.BUSINESS_SLUG
    assert user.email == seed_local_dev.OPERATOR_EMAIL.lower()
    assert user.hashed_password != FAKE_PASSWORD and verify_password(FAKE_PASSWORD, user.hashed_password)
    assert (access.user_id, access.tenant_id, access.role.value) == (user.id, tenant.id, "owner")


def test_running_it_again_creates_nothing_and_never_asks_for_a_password(session):
    first = _Passwords()
    seed_local_dev.seed(session, password_provider=first)
    session.commit()
    second = _Passwords()

    result = seed_local_dev.seed(session, password_provider=second)

    assert result == seed_local_dev.SeedResult(False, False, False, False)
    assert (first.calls, second.calls) == (1, 0)
    assert [_count(session, m) for m in (Tenant, Business, User, TenantAccess)] == [1, 1, 1, 1]


def test_an_existing_operator_keeps_its_password(session):
    original = hash_password("the-operator-chose-this")
    session.add(User(email=seed_local_dev.OPERATOR_EMAIL, hashed_password=original))
    session.flush()
    passwords = _Passwords()

    result = seed_local_dev.seed(session, password_provider=passwords)

    assert result.user_created is False and passwords.calls == 0
    assert session.scalars(select(User)).one().hashed_password == original
    assert result.access_created is True


def test_a_database_with_another_tenant_is_refused_and_left_untouched(session, tenant, business):
    before = (tenant.name, business.name, business.slug)

    with pytest.raises(SeedRefused, match="other tenant"):
        seed_local_dev.seed(session, password_provider=_Passwords())

    assert (tenant.name, business.name, business.slug) == before
    assert session.get(Tenant, seed_local_dev.TENANT_ID) is None
    assert [_count(session, m) for m in (Tenant, Business, User, TenantAccess)] == [1, 1, 0, 0]


def test_a_real_tenant_with_the_seeds_id_is_never_modified(session):
    session.add(Tenant(id=seed_local_dev.TENANT_ID, name="A real agency"))
    session.flush()

    with pytest.raises(SeedRefused, match="not the seed's own"):
        seed_local_dev.seed(session, password_provider=_Passwords())

    assert session.get(Tenant, seed_local_dev.TENANT_ID).name == "A real agency"
    assert [_count(session, m) for m in (Business, User, TenantAccess)] == [0, 0, 0]


def test_a_real_business_with_the_seeds_id_is_never_modified(session):
    seed_local_dev.seed(session, password_provider=_Passwords())
    business = session.get(Business, seed_local_dev.BUSINESS_ID)
    business.name = "A real bakery"
    session.flush()

    with pytest.raises(SeedRefused, match="not the seed's own"):
        seed_local_dev.seed(session, password_provider=_Passwords())

    assert session.get(Business, seed_local_dev.BUSINESS_ID).name == "A real bakery"


def test_the_seed_ids_are_fixed_fictional_and_not_production():
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, "https://gwa-local.example/dev-seed")
    assert seed_local_dev.TENANT_ID == uuid.uuid5(namespace, "tenant")
    assert seed_local_dev.BUSINESS_ID == uuid.uuid5(namespace, "business")
    assert COSITAS_BUSINESS_ID not in (seed_local_dev.TENANT_ID, seed_local_dev.BUSINESS_ID)
    assert seed_local_dev.OPERATOR_EMAIL.endswith(".example")  # RFC 2606: no real mailbox
    assert "ficticio" in seed_local_dev.TENANT_NAME and "ficticia" in seed_local_dev.BUSINESS_NAME
