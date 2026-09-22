import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.user import User


class UserSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A logged-in browser session (A2). Named `UserSession`, not `Session`,
    to avoid any collision with `sqlalchemy.orm.Session` (the DB session
    every repository already takes as a constructor argument) — a real risk
    of confusion this codebase's own naming conventions never had to guard
    against before.

    `token_hash` is the SHA-256 digest of the opaque bearer token actually
    held in the browser's cookie (app.security.session_tokens) — the raw
    token itself is NEVER persisted anywhere (see that module's own
    docstring for why a fast digest, not a slow KDF, is the right primitive
    here). `csrf_token`, by contrast, IS stored in plain: it is never used
    as a credential on its own (only compared for equality against a
    header the client echoes back once a session is already established —
    see app.dependencies' CSRF check), so hashing it would add cost with no
    security benefit.

    `revoked_at` is set (never the row deleted) on logout — deleting on
    logout would make "was this session ever valid, and when did it stop
    being so" unanswerable later, the same audit-trail reasoning
    BusinessAsset.unavailable_reason and CreativeBudget.record_failure
    already apply elsewhere in this codebase."""

    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="sessions")
