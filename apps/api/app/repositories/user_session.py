from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.user_session import UserSession


class UserSessionRepository:
    """Not tenant-scoped (a session belongs to a User, not a Tenant — see
    app.db.models.user_session.UserSession)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, user_session: UserSession) -> UserSession:
        self.session.add(user_session)
        self.session.flush()
        return user_session

    def get_valid_by_token_hash(self, token_hash: str, *, now: datetime | None = None) -> UserSession | None:
        """A session that exists, was never revoked, and has not expired —
        the one query every authenticated request makes. `now` is
        injectable so tests can exercise real expiry without sleeping."""
        now = now or datetime.now(UTC)
        stmt = select(UserSession).where(
            UserSession.token_hash == token_hash,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
        )
        return self.session.scalars(stmt).first()

    def revoke(self, user_session: UserSession, *, now: datetime | None = None) -> None:
        user_session.revoked_at = now or datetime.now(UTC)
        self.session.flush()

    def revoke_by_token_hash(self, token_hash: str) -> bool:
        """Logout — idempotent: revoking an already-revoked or unknown
        token is a no-op, never an error (a caller cannot be expected to
        know its own session's current state before asking to end it)."""
        stmt = select(UserSession).where(UserSession.token_hash == token_hash, UserSession.revoked_at.is_(None))
        user_session = self.session.scalars(stmt).first()
        if user_session is None:
            return False
        self.revoke(user_session)
        return True

    def revoke_all_for_user(self, user_id: UUID) -> None:
        """Every currently-valid session for this user — "log out
        everywhere," used only by the A2 cutover / an operator action, not
        by any route in this PR."""
        now = datetime.now(UTC)
        stmt = select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        for user_session in self.session.scalars(stmt).all():
            user_session.revoked_at = now
        self.session.flush()
