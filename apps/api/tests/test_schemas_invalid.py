"""Bad input is rejected: missing required fields, malformed values, and
the cross-field business rules (approval consistency, execution
type/target consistency)."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.enums import (
    BusinessVertical,
    ConfigOrigin,
    ExecutionType,
    TemplateKind,
    WorkflowVersionStatus,
)
from app.schemas.business import BusinessCreate
from app.schemas.credential import CredentialCreate
from app.schemas.execution import ExecutionCreate
from app.schemas.integration import IntegrationCreate
from app.schemas.template import TemplateCreate
from app.schemas.tenant import TenantCreate
from app.schemas.user import UserCreate
from app.schemas.workflow import WorkflowCreate
from app.schemas.workflow_version import WorkflowVersionCreate


def test_tenant_requires_name():
    with pytest.raises(ValidationError):
        TenantCreate()


def test_tenant_rejects_blank_name():
    with pytest.raises(ValidationError):
        TenantCreate(name="   ")


def test_tenant_rejects_unknown_field():
    with pytest.raises(ValidationError):
        TenantCreate(name="Acme", extra_field="not allowed")


def test_user_rejects_invalid_email():
    with pytest.raises(ValidationError):
        UserCreate(tenant_id=uuid.uuid4(), email="not-an-email")


def test_user_requires_tenant_id():
    with pytest.raises(ValidationError):
        UserCreate(email="team@acme.studio")


def test_business_rejects_short_description():
    with pytest.raises(ValidationError):
        BusinessCreate(
            tenant_id=uuid.uuid4(),
            name="Reformas Valencia",
            vertical=BusinessVertical.HOME_RENOVATION,
            raw_description="Too short",
        )


def test_business_rejects_unknown_vertical():
    with pytest.raises(ValidationError):
        BusinessCreate(
            tenant_id=uuid.uuid4(),
            name="Reformas Valencia",
            vertical="not_a_real_vertical",
            raw_description="Empresa de reformas integrales en Valencia, servicios residenciales.",
        )


def test_business_requires_name():
    with pytest.raises(ValidationError):
        BusinessCreate(
            tenant_id=uuid.uuid4(),
            vertical=BusinessVertical.HOME_RENOVATION,
            raw_description="Empresa de reformas integrales en Valencia, servicios residenciales.",
        )


def test_workflow_rejects_blank_name():
    with pytest.raises(ValidationError):
        WorkflowCreate(tenant_id=uuid.uuid4(), business_id=uuid.uuid4(), name="   ")


def test_workflow_version_rejects_empty_definition():
    with pytest.raises(ValidationError):
        WorkflowVersionCreate(
            tenant_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            version=1,
            definition={},
            created_by=ConfigOrigin.AI,
        )


def test_workflow_version_rejects_zero_version():
    with pytest.raises(ValidationError):
        WorkflowVersionCreate(
            tenant_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            version=0,
            definition={"steps": []},
            created_by=ConfigOrigin.AI,
        )


def test_workflow_version_approved_requires_approver():
    with pytest.raises(ValidationError, match="approved_by_id and approved_at are required"):
        WorkflowVersionCreate(
            tenant_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            version=1,
            definition={"steps": []},
            created_by=ConfigOrigin.AI,
            status=WorkflowVersionStatus.APPROVED,
        )


def test_workflow_version_published_requires_approved_at_too():
    with pytest.raises(ValidationError, match="approved_by_id and approved_at are required"):
        WorkflowVersionCreate(
            tenant_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            version=1,
            definition={"steps": []},
            created_by=ConfigOrigin.AI,
            status=WorkflowVersionStatus.PUBLISHED,
            approved_by_id=uuid.uuid4(),
        )


def test_integration_rejects_unknown_provider():
    with pytest.raises(ValidationError):
        IntegrationCreate(tenant_id=uuid.uuid4(), business_id=uuid.uuid4(), provider="not_a_provider")


def test_integration_requires_provider():
    with pytest.raises(ValidationError):
        IntegrationCreate(tenant_id=uuid.uuid4(), business_id=uuid.uuid4())


def test_credential_rejects_blank_secret():
    with pytest.raises(ValidationError):
        CredentialCreate(tenant_id=uuid.uuid4(), integration_id=uuid.uuid4(), secret="")


def test_credential_never_accepts_pre_encrypted_value_field():
    # CredentialCreate has no `encrypted_value` field at all — passing one
    # must be rejected as an unknown field, not silently stored.
    with pytest.raises(ValidationError):
        CredentialCreate(
            tenant_id=uuid.uuid4(),
            integration_id=uuid.uuid4(),
            secret="x",
            encrypted_value="already-encrypted",
        )


def test_execution_workflow_run_requires_workflow_id():
    with pytest.raises(ValidationError, match="workflow_run executions require workflow_id"):
        ExecutionCreate(tenant_id=uuid.uuid4(), business_id=uuid.uuid4(), type=ExecutionType.WORKFLOW_RUN)


def test_execution_workflow_run_rejects_website_id():
    with pytest.raises(ValidationError, match="workflow_run executions require workflow_id"):
        ExecutionCreate(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            type=ExecutionType.WORKFLOW_RUN,
            workflow_id=uuid.uuid4(),
            website_id=uuid.uuid4(),
        )


def test_execution_website_build_requires_website_id():
    with pytest.raises(ValidationError, match="website_build executions require website_id"):
        ExecutionCreate(tenant_id=uuid.uuid4(), business_id=uuid.uuid4(), type=ExecutionType.WEBSITE_BUILD)


def test_execution_rejects_finished_before_started():
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="finished_at must not be before started_at"):
        ExecutionCreate(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            type=ExecutionType.WEBSITE_BUILD,
            website_id=uuid.uuid4(),
            started_at=now,
            finished_at=now.replace(year=now.year - 1),
        )


def test_template_rejects_empty_definition():
    with pytest.raises(ValidationError):
        TemplateCreate(tenant_id=uuid.uuid4(), kind=TemplateKind.WEBSITE_BLOCK, definition={})


def test_template_rejects_negative_usage_count():
    with pytest.raises(ValidationError):
        TemplateCreate(
            tenant_id=uuid.uuid4(),
            kind=TemplateKind.WEBSITE_BLOCK,
            definition={"blocks": ["hero"]},
            usage_count=-1,
        )
