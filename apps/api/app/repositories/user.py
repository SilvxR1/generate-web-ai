from uuid import UUID

from sqlalchemy import select

from app.db.models.user import User
from app.repositories.base import TenantScopedRepository


class UserRepository(TenantScopedRepository[User]):
    model = User

    def get_by_email(self, tenant_id: UUID, email: str) -> User | None:
        stmt = select(User).where(User.tenant_id == tenant_id, User.email == email)
        return self.session.scalars(stmt).first()
