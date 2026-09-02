from app.db.models.template import Template
from app.repositories.base import TenantScopedRepository


class TemplateRepository(TenantScopedRepository[Template]):
    model = Template
