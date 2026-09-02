from app.db.models.internal_notification import InternalNotification
from app.repositories.base import TenantScopedRepository


class InternalNotificationRepository(TenantScopedRepository[InternalNotification]):
    model = InternalNotification
