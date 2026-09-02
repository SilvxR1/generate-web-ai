"""Sweep of the fields each Create schema actually requires, independent
of the specific-scenario tests in test_schemas_invalid.py."""

import uuid

import pytest
from pydantic import ValidationError

from app.domain.enums import IntegrationProvider
from app.schemas.execution import ExecutionCreate
from app.schemas.integration import IntegrationCreate
from app.schemas.template import TemplateCreate
from app.schemas.website import WebsiteCreate
from app.schemas.workflow import WorkflowCreate
from app.schemas.workflow_version import WorkflowVersionCreate


def test_website_requires_tenant_and_business_id():
    with pytest.raises(ValidationError):
        WebsiteCreate()


def test_website_allows_omitting_optional_fields():
    website = WebsiteCreate(tenant_id=uuid.uuid4(), business_id=uuid.uuid4())
    assert website.deploy_url is None
    assert website.config is None


def test_workflow_requires_name():
    with pytest.raises(ValidationError):
        WorkflowCreate(tenant_id=uuid.uuid4(), business_id=uuid.uuid4())


def test_workflow_version_requires_definition_and_created_by():
    with pytest.raises(ValidationError):
        WorkflowVersionCreate(tenant_id=uuid.uuid4(), workflow_id=uuid.uuid4(), version=1)


def test_integration_requires_business_and_tenant_id():
    with pytest.raises(ValidationError):
        IntegrationCreate(provider=IntegrationProvider.WEBHOOK)


def test_execution_requires_type():
    with pytest.raises(ValidationError):
        ExecutionCreate(tenant_id=uuid.uuid4(), business_id=uuid.uuid4())


def test_template_requires_kind_and_definition():
    with pytest.raises(ValidationError):
        TemplateCreate(tenant_id=uuid.uuid4())
