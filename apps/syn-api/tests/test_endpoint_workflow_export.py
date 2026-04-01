"""Tests for workflow export HTTP endpoint wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from syn_api.routes.workflows.queries import (
    ExportManifestResponse,
    export_workflow_endpoint,
)
from syn_api.types import Err, Ok, WorkflowError


async def test_export_endpoint_success_package() -> None:
    manifest = ExportManifestResponse(
        format="package",
        workflow_id="wf-123",
        workflow_name="Test Workflow",
        files={
            "workflow.yaml": "id: wf-123\nname: Test Workflow\n",
            "phases/phase1.md": "---\nmodel: sonnet\n---\n\nDo stuff.\n",
            "README.md": "# Test Workflow\n",
        },
    )
    with patch(
        "syn_api.routes.workflows.queries.export_workflow",
        new_callable=AsyncMock,
        return_value=Ok(manifest),
    ):
        result = await export_workflow_endpoint("wf-123", format="package")

    assert result.format == "package"
    assert result.workflow_id == "wf-123"
    assert len(result.files) == 3


async def test_export_endpoint_success_plugin() -> None:
    manifest = ExportManifestResponse(
        format="plugin",
        workflow_id="wf-456",
        workflow_name="Plugin Workflow",
        files={
            "syntropic137.yaml": "manifest_version: 1\n",
            "workflows/plugin-workflow/workflow.yaml": "id: wf-456\n",
            "commands/syn-plugin-workflow.md": "---\nmodel: sonnet\n---\n\n...\n",
            "README.md": "# Plugin\n",
        },
    )
    with patch(
        "syn_api.routes.workflows.queries.export_workflow",
        new_callable=AsyncMock,
        return_value=Ok(manifest),
    ):
        result = await export_workflow_endpoint("wf-456", format="plugin")

    assert result.format == "plugin"
    assert result.workflow_id == "wf-456"
    assert "syntropic137.yaml" in result.files


async def test_export_endpoint_not_found() -> None:
    with (
        patch(
            "syn_api.routes.workflows.queries.export_workflow",
            new_callable=AsyncMock,
            return_value=Err(WorkflowError.NOT_FOUND, message="Workflow not-found not found"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await export_workflow_endpoint("not-found", format="package")

    assert exc_info.value.status_code == 404
