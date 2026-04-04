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
        result = await create_workflow_endpoint(CreateWorkflowRequest(name="My Workflow"))
    assert result.id == "wf-abc-123"
    assert result.name == "My Workflow"
    assert result.workflow_type == "custom"
    assert result.status == "created"


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
    assert result.id == "wf-full"
    assert result.workflow_type == "research"
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args
    assert call_kwargs.kwargs.get("workflow_type") == "research" or (
        call_kwargs[1].get("workflow_type") == "research"
    )


def test_create_workflow_request_rejects_invalid_id() -> None:
    """Client-supplied IDs must match the safe character pattern."""
    from pydantic import ValidationError

    # Empty string
    with pytest.raises(ValidationError):
        CreateWorkflowRequest(name="Test", id="")

    # Special characters
    with pytest.raises(ValidationError):
        CreateWorkflowRequest(name="Test", id="../../etc/passwd")

    # Starts with dash
    with pytest.raises(ValidationError):
        CreateWorkflowRequest(name="Test", id="-bad-start")


def test_create_workflow_request_accepts_valid_ids() -> None:
    """Valid slug-style and UUID-style IDs should be accepted."""
    req = CreateWorkflowRequest(name="Test", id="research-v1")
    assert req.id == "research-v1"

    req2 = CreateWorkflowRequest(name="Test", id="my.workflow_v2")
    assert req2.id == "my.workflow_v2"

    # None is fine (auto-generated)
    req3 = CreateWorkflowRequest(name="Test")
    assert req3.id is None


async def test_create_workflow_endpoint_service_error() -> None:
    with (
        patch(
            "syn_api.routes.workflows.commands.create_workflow",
            new_callable=AsyncMock,
            return_value=Err(WorkflowError.INVALID_INPUT, message="bad workflow"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await create_workflow_endpoint(CreateWorkflowRequest(name="Bad Workflow"))
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
        result = await validate_yaml_endpoint(ValidateYamlRequest(content="name: Test WF\ntype: custom\n"))
    assert result.valid is True
    assert result.name == "Test WF"
    assert result.phase_count == 2


async def test_validate_yaml_endpoint_invalid_yaml() -> None:
    with patch(
        "syn_api.routes.workflows.commands.validate_yaml",
        new_callable=AsyncMock,
        return_value=Ok(WorkflowValidation(valid=False, errors=["Missing required field: name"])),
    ):
        result = await validate_yaml_endpoint(ValidateYamlRequest(content="name: Missing Required Fields\n"))
    assert result.valid is False
    assert len(result.errors) == 1


async def test_validate_yaml_endpoint_service_error() -> None:
    with (
        patch(
            "syn_api.routes.workflows.commands.validate_yaml",
            new_callable=AsyncMock,
            return_value=Err(WorkflowError.NOT_FOUND, message="file not found"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await validate_yaml_endpoint(ValidateYamlRequest(content="invalid: content\n"))
    assert exc_info.value.status_code == 400


# --- delete_workflow_endpoint ---


async def test_delete_workflow_endpoint_success() -> None:
    from syn_api.routes.workflows.commands import delete_workflow_endpoint

    with patch(
        "syn_api.routes.workflows.commands.delete_workflow",
        new_callable=AsyncMock,
        return_value=Ok(None),
    ):
        result = await delete_workflow_endpoint("wf-abc-123")
    assert result.workflow_id == "wf-abc-123"
    assert result.status == "archived"


async def test_delete_workflow_endpoint_not_found() -> None:
    from syn_api.routes.workflows.commands import delete_workflow_endpoint

    with (
        patch(
            "syn_api.routes.workflows.commands.delete_workflow",
            new_callable=AsyncMock,
            return_value=Err(WorkflowError.NOT_FOUND, message="not found"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await delete_workflow_endpoint("nonexistent")
    assert exc_info.value.status_code == 404


async def test_delete_workflow_endpoint_has_active_executions() -> None:
    from syn_api.routes.workflows.commands import delete_workflow_endpoint

    with (
        patch(
            "syn_api.routes.workflows.commands.delete_workflow",
            new_callable=AsyncMock,
            return_value=Err(
                WorkflowError.HAS_ACTIVE_EXECUTIONS,
                message="Cannot archive: 1 active execution(s)",
            ),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await delete_workflow_endpoint("wf-busy")
    assert exc_info.value.status_code == 409


async def test_delete_workflow_endpoint_already_archived() -> None:
    from syn_api.routes.workflows.commands import delete_workflow_endpoint

    with (
        patch(
            "syn_api.routes.workflows.commands.delete_workflow",
            new_callable=AsyncMock,
            return_value=Err(WorkflowError.ALREADY_ARCHIVED, message="already archived"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await delete_workflow_endpoint("wf-old")
    assert exc_info.value.status_code == 409
