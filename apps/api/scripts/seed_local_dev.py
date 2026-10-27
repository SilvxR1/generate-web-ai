"""DEV-3 local development seed: one fictional tenant, one fictional business
and one local operator, for a FRESH local PostgreSQL database (the gwa-local
Docker Compose project, see docs/local-development.md). Never for production,
and never for a database that already holds other tenants.

    cd apps/api && .venv/bin/python scripts/seed_local_dev.py --confirm-local-seed

Before connecting, it refuses unless:
- --confirm-local-seed is passed;
- ENVIRONMENT is exactly `development`;
- DATABASE_URL is PostgreSQL on a loopback host (not SQLite, not a compose
  service name, not a remote host);
- neither the host, database nor user name looks like production.

After connecting, it refuses (writing nothing) when the database holds any
tenant other than the fictional one, or when a row with one of the seed's
fixed ids is not the seed's own.

Idempotent: every row uses a fixed, non-production id, so re-running it
finds them and creates nothing twice. An existing operator's password is
never changed. The password is prompted for (hidden), hashed with the same
app.security.passwords.hash_password that /auth/login checks, and never
printed. The output names the ids and the email, never DATABASE_URL.
"""

import argparse
import ipaddress
import re
import sys
import uuid
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))  # so `.venv/bin/python scripts/...` works without a PYTHONPATH

from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.models.business import Business  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.tenant_access import TenantAccess  # noqa: E402
from app.db.models.user import User  # noqa: E402
from app.domain.enums import BusinessStatus, BusinessVertical, UserRole  # noqa: E402
from app.repositories.tenant import TenantRepository  # noqa: E402
from app.repositories.tenant_access import TenantAccessRepository  # noqa: E402
from app.repositories.user import UserRepository  # noqa: E402
from app.security.passwords import PasswordTooLongError, hash_password  # noqa: E402

# Fixed ids derived from a seed-only namespace: stable across runs (so the
# seed is idempotent) and never the id of a real production row.
_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://gwa-local.example/dev-seed")
TENANT_ID = uuid.uuid5(_NAMESPACE, "tenant")
BUSINESS_ID = uuid.uuid5(_NAMESPACE, "business")
TENANT_NAME = "GWA Local Dev (ficticio)"
BUSINESS_NAME = "Panadería La Prueba (ficticia)"
BUSINESS_SLUG = "panaderia-la-prueba-dev"
# `.example` is reserved (RFC 2606): no real mailbox, and login's EmailStr accepts it.
OPERATOR_EMAIL = "operator@gwa-local.example"

_LOOPBACK_NAMES = frozenset({"localhost", "ip6-localhost"})
_PRODUCTION_LOOKING = re.compile(r"prod|railway|rlwy|cositas|cloudflare|neon\.tech|supabase|amazonaws", re.I)


class SeedRefused(Exception):
    """The seed would not be safe here; nothing was written."""


@dataclass(frozen=True)
class SeedResult:
    tenant_created: bool
    business_created: bool
    user_created: bool
    access_created: bool


def check_target(environment: str, database_url: str) -> None:
    """Raises SeedRefused unless this is a local development PostgreSQL. The
    messages never include the URL, the host or any credential."""
    if environment != "development":
        raise SeedRefused("ENVIRONMENT must be exactly 'development'")
    try:
        url = make_url(database_url)
    except Exception as exc:  # its message would echo the URL
        raise SeedRefused("DATABASE_URL could not be parsed") from exc
    if url.get_backend_name() != "postgresql":
        raise SeedRefused("DATABASE_URL must be PostgreSQL (the local gwa-local database), not SQLite or other")
    if not _is_loopback(url.host):
        raise SeedRefused("DATABASE_URL host must be loopback (localhost, 127.0.0.1 or ::1)")
    for part in (url.host, url.database, url.username):
        if part and _PRODUCTION_LOOKING.search(part):
            raise SeedRefused("DATABASE_URL host, database or user name looks like production")


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False  # a Unix socket or default host can't be told apart from a tunnel; be explicit
    host = host.strip("[]").lower()
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def seed(session: Session, *, password_provider) -> SeedResult:
    """Creates whatever is missing, inside the caller's transaction (flush
    only, never commit). `password_provider()` is only called when the
    operator does not exist yet."""
    tenants = TenantRepository(session)
    others = [t for t in tenants.list() if t.id != TENANT_ID]
    if others:
        raise SeedRefused(
            f"the database already holds {len(others)} other tenant(s); the seed only runs on a fresh local "
            "database (start the gwa-local Compose project, see docs/local-development.md)"
        )

    tenant = tenants.get(TENANT_ID)
    tenant_created = tenant is None
    if tenant is None:
        tenant = Tenant(id=TENANT_ID, name=TENANT_NAME)
        session.add(tenant)
        session.flush()
    elif tenant.name != TENANT_NAME:
        raise SeedRefused("a tenant with the seed's id exists but is not the seed's own; it was left untouched")

    business = session.get(Business, BUSINESS_ID)  # by id across tenants: a clash elsewhere must be seen
    business_created = business is None
    if business is None:
        session.add(
            Business(
                id=BUSINESS_ID,
                tenant_id=TENANT_ID,
                name=BUSINESS_NAME,
                slug=BUSINESS_SLUG,
                vertical=BusinessVertical.RESTAURANT,
                raw_description=(
                    "Negocio ficticio para desarrollo local: una panadería de barrio inventada. "
                    "No corresponde a ningún cliente real."
                ),
                status=BusinessStatus.DRAFT,
            )
        )
        session.flush()
    elif business.tenant_id != TENANT_ID or business.name != BUSINESS_NAME:
        raise SeedRefused("a business with the seed's id exists but is not the seed's own; it was left untouched")

    users = UserRepository(session)
    user = users.get_by_email(OPERATOR_EMAIL)
    user_created = user is None
    if user is None:
        password = password_provider()
        try:
            hashed = hash_password(password)
        except PasswordTooLongError as exc:
            raise SeedRefused(str(exc)) from exc
        finally:
            del password
        user = User(email=OPERATOR_EMAIL, hashed_password=hashed)
        session.add(user)
        session.flush()

    access_repo = TenantAccessRepository(session)
    access_created = access_repo.get(user_id=user.id, tenant_id=TENANT_ID) is None
    if access_created:
        session.add(TenantAccess(user_id=user.id, tenant_id=TENANT_ID, role=UserRole.OWNER))
        session.flush()

    return SeedResult(tenant_created, business_created, user_created, access_created)


def _prompt_password() -> str:
    password = getpass(f"Local password for {OPERATOR_EMAIL} (input hidden, never logged): ")
    if not password:
        raise SeedRefused("empty password")
    if getpass("Confirm password: ") != password:
        raise SeedRefused("passwords did not match")
    return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--confirm-local-seed",
        action="store_true",
        help="Required: confirms this targets the fresh local gwa-local database.",
    )
    args = parser.parse_args(argv)

    from app.config import settings
    from app.db.session import make_engine, make_session_factory

    try:
        if not args.confirm_local_seed:
            raise SeedRefused("pass --confirm-local-seed to confirm this targets the fresh local database")
        check_target(settings.environment, settings.database_url)
    except SeedRefused as exc:
        print(f"REFUSING: {exc}. Nothing written.", file=sys.stderr)
        return 1

    engine = make_engine(settings.database_url)
    session = make_session_factory(engine)()
    try:
        result = seed(session, password_provider=_prompt_password)
        session.commit()
    except SeedRefused as exc:
        session.rollback()
        print(f"REFUSING: {exc}. Nothing written.", file=sys.stderr)
        return 1
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()

    print("DONE (local development seed).")
    print(f"  tenant_id:   {TENANT_ID}  created this run: {result.tenant_created}")
    print(f"  business_id: {BUSINESS_ID}  created this run: {result.business_created}")
    print(f"  operator:    {OPERATOR_EMAIL}  created this run: {result.user_created}")
    print(f"  access:      owner  created this run: {result.access_created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
