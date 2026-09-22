from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.user import User


class UserRepository:
    """Not tenant-scoped, by definition (A2): a User is a person who may
    hold access to several tenants, so there is no single tenant_id to
    scope by — see app.db.models.user.User's own docstring. Mirrors
    TenantRepository's own "root entity, not tenant-scoped" shape."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user

    def get(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        """Case-insensitive on purpose — email as a login identity is
        conventionally treated case-insensitively (RFC 5321 makes the
        local part case-sensitive in theory, but no real mail provider in
        practice does, and a login form that silently fails on
        capitalization is a real, common support burden). `func.lower`
        matches on both sides so this works the same regardless of how
        the email was originally stored."""
        stmt = select(User).where(func.lower(User.email) == email.strip().lower())
        return self.session.scalars(stmt).first()
