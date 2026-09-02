"""Every Create schema accepts a well-formed payload for its entity."""

import uuid
from datetime import UTC, datetime

from app.domain.enums import (
    BusinessStatus,
    BusinessVertical,
    ConfigOrigin,
    DeployTarget,
    ExecutionStatus,
    ExecutionType,
    IntegrationProvider,
    IntegrationStatus,
    TemplateKind,
    UserRole,
    WebsiteStatus,
    WorkflowStatus,
    WorkflowVersionStatus,
)
from app.schemas.business import BusinessCreate
from app.schemas.credential import CredentialCreate
from app.schemas.execution import ExecutionCreate
from app.schemas.integration import IntegrationCreate
from app.schemas.template import TemplateCreate
from app.schemas.tenant import TenantCreate
from app.schemas.user import UserCreate
from app.schemas.website import WebsiteCreate
from app.schemas.workflow import WorkflowCreate
from app.schemas.workflow_version import WorkflowVersionCreate


def test_tenant_create_valid():
    tenant = TenantCreate(name="Acme Studio")
    assert tenant.name == "Acme Studio"


def test_user_create_valid():
    user = UserCreate(tenant_id=uuid.uuid4(), email="team@acme.studio", role=UserRole.OWNER)
    assert user.role is UserRole.OWNER


def test_business_create_valid():
    business = BusinessCreate(
        tenant_id=uuid.uuid4(),
        name="Reformas Valencia",
        slug="reformas-valencia",
        vertical=BusinessVertical.HOME_RENOVATION,
        raw_description="Empresa de reformas integrales en Valencia con clientes residenciales.",
        status=BusinessStatus.DRAFT,
    )
    assert business.vertical is BusinessVertical.HOME_RENOVATION


def test_website_create_valid():
    website = WebsiteCreate(
        tenant_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        deploy_target=DeployTarget.CLOUDFLARE,
        deploy_url="https://reformas-valencia.example.com",
        status=WebsiteStatus.LIVE,
        config={"pages": []},
    )
    assert str(website.deploy_url).startswith("https://reformas-valencia.example.com")


def test_workflow_create_valid():
    workflow = WorkflowCreate(tenant_id=uuid.uuid4(), business_id=uuid.uuid4(), name="Lead capture")
    assert workflow.status is WorkflowStatus.DRAFT


def test_workflow_version_create_valid_draft():
    version = WorkflowVersionCreate(
        tenant_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        version=1,
        definition={"steps": [{"type": "webhook"}]},
        created_by=ConfigOrigin.AI,
        status=WorkflowVersionStatus.DRAFT,
    )
    assert version.status is WorkflowVersionStatus.DRAFT


def test_workflow_version_create_valid_approved():
    version = WorkflowVersionCreate(
        tenant_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        version=2,
        definition={"steps": [{"type": "webhook"}]},
        created_by=ConfigOrigin.HUMAN,
        status=WorkflowVersionStatus.APPROVED,
        approved_by_id=uuid.uuid4(),
        approved_at=datetime.now(UTC),
    )
    assert version.status is WorkflowVersionStatus.APPROVED


def test_integration_create_valid():
    integration = IntegrationCreate(
        tenant_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        provider=IntegrationProvider.SLACK,
        status=IntegrationStatus.CONNECTED,
        scopes=["chat:write"],
    )
    assert integration.provider is IntegrationProvider.SLACK


def test_credential_create_valid():
    credential = CredentialCreate(tenant_id=uuid.uuid4(), integration_id=uuid.uuid4(), secret="super-secret-token")
    assert credential.secret == "super-secret-token"


def test_execution_create_valid_workflow_run():
    execution = ExecutionCreate(
        tenant_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        type=ExecutionType.WORKFLOW_RUN,
        status=ExecutionStatus.SUCCESS,
        workflow_id=uuid.uuid4(),
    )
    assert execution.website_id is None


def test_execution_create_valid_website_build():
    execution = ExecutionCreate(
        tenant_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        type=ExecutionType.WEBSITE_BUILD,
        website_id=uuid.uuid4(),
    )
    assert execution.workflow_id is None


def test_template_create_valid():
    template = TemplateCreate(
        tenant_id=uuid.uuid4(),
        kind=TemplateKind.WORKFLOW_PATTERN,
        vertical=None,
        definition={"steps": ["webhook", "notify"]},
    )
    assert template.usage_count == 0
