"""Tests for workflow HTTP endpoint wrappers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from syn_api.routes.workflows.commands import (
    CreateWorkflowRequest,
    ValidateYamlRequest,
    create_workflow_endpoint,
    validate_yaml_endpoint,
)
from syn_api.types import Err, Ok, WorkflowError, WorkflowValidation


# --- create_workflow_endpoint ---


async def test_create_workflow_endpoint_success() -> None:
    with patch(
        "syn_api.routes.workflows.commands.create_workflow",
        new_callable=AsyncMock,
        return_value=Ok("wf-abc-123"),
    ):
        result = await create_workflow_endpoint(
            CreateWorkflowRequest(name="My Workflow")
        )
    assert result["id"] == "wf-abc-123"
    assert result["name"] == "My Workflow"
    assert result["workflow_type"] == "custom"
    assert result["status"] == "created"


async def test_create_workflow_endpoint_with_all_fields() -> None:
    with patch(
        "syn_api.routes.workflows.commands.create_workflow",
        new_callable=AsyncMock,
        return_value=Ok("wf-full"),
    ) as mock_create:
        result = await create_workflow_endpoint(
            CreateWorkflowRequest(
                name="Full Workflow",
                workflow_type="research",
                classification="complex",
                repository_url="https://github.com/test/repo",
                repository_ref="develop",
                description="A full workflow",
            )
        )
    assert result["id"] == "wf-full"
    assert result["workflow_type"] == "research"
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args
    assert call_kwargs.kwargs.get("workflow_type") == "research" or (
        call_kwargs[1].get("workflow_type") == "research"
    )


async def test_create_workflow_endpoint_service_error() -> None:
    with patch(
        "syn_api.routes.workflows.commands.create_workflow",
        new_callable=AsyncMock,
        return_value=Err(WorkflowError.INVALID_INPUT, message="bad workflow"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await create_workflow_endpoint(
                CreateWorkflowRequest(name="Bad Workflow")
            )
    assert exc_info.value.status_code == 400
    assert "bad workflow" in str(exc_info.value.detail)


# --- validate_yaml_endpoint ---


async def test_validate_yaml_endpoint_success() -> None:
    with patch(
        "syn_api.routes.workflows.commands.validate_yaml",
        new_callable=AsyncMock,
        return_value=Ok(
            WorkflowValidation(
                valid=True,
                name="Test WF",
                workflow_type="custom",
                phase_count=2,
            )
        ),
    ):
        result = await validate_yaml_endpoint(
            ValidateYamlRequest(file="/tmp/test.yaml")
        )
    assert result["valid"] is True
    assert result["name"] == "Test WF"
    assert result["phase_count"] == 2


async def test_validate_yaml_endpoint_invalid_yaml() -> None:
    with patch(
        "syn_api.routes.workflows.commands.validate_yaml",
        new_callable=AsyncMock,
        return_value=Ok(
            WorkflowValidation(valid=False, errors=["Missing required field: name"])
        ),
    ):
        result = await validate_yaml_endpoint(
            ValidateYamlRequest(file="/tmp/bad.yaml")
        )
    assert result["valid"] is False
    errors = result["errors"]
    assert isinstance(errors, list)
    assert len(errors) == 1


async def test_validate_yaml_endpoint_service_error() -> None:
    with patch(
        "syn_api.routes.workflows.commands.validate_yaml",
        new_callable=AsyncMock,
        return_value=Err(WorkflowError.NOT_FOUND, message="file not found"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await validate_yaml_endpoint(
                ValidateYamlRequest(file="/nonexistent.yaml")
            )
    assert exc_info.value.status_code == 400
