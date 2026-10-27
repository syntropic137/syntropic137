"""A phase's workspace memory request through the API: install, start, read back, wiring (okrs-51p.30).

The wiring test builds the workspace service through the same function
`get_execution_processor` calls: a ledger that exists but is never passed in
production would leave every unit test green and the host over-committed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from syn_adapters.workspace_backends.service.workspace_service import WorkspaceServiceConfig
from syn_api._wiring import build_workspace_service
from syn_api._wiring_workspace_memory import get_workspace_memory_ledger
from syn_api.routes.workflows.phase_defs import _build_phase_defs
from syn_domain.contexts.orchestration import WorkspaceMemoryOverCapError, WorkspaceResourceRequest
from syn_shared.settings import get_settings
from syn_shared.settings.workspace import WorkspaceSettings

pytestmark = pytest.mark.unit


def test_the_production_workspace_service_reserves_from_the_process_ledger() -> None:
    first = build_workspace_service(WorkspaceServiceConfig.from_settings(WorkspaceSettings()), None)
    second = build_workspace_service(
        WorkspaceServiceConfig.from_settings(WorkspaceSettings()), None
    )

    ledger = get_workspace_memory_ledger()
    # One per process, not one per service: a service is built per launch.
    assert first._memory_ledger is ledger
    assert second._memory_ledger is ledger
    settings = get_settings()
    assert ledger.capacity_mb == (
        settings.execution.max_concurrent * settings.workspace.memory_limit_mb
    )


def test_install_refuses_a_request_above_the_deployment_ceiling() -> None:
    """Unset SYN_WORKSPACE_MEMORY_MAX_MB: nothing above the 4096 default installs."""
    with pytest.raises(WorkspaceMemoryOverCapError, match="build"):
        _build_phase_defs(
            [{"phase_id": "build", "name": "Build", "order": 1, "resources": {"memory_mb": 12288}}]
        )


def test_install_refuses_a_malformed_request_rather_than_dropping_it() -> None:
    with pytest.raises(ValueError, match="memory"):
        _build_phase_defs(
            [{"phase_id": "build", "name": "Build", "order": 1, "resources": {"memory": 2048}}]
        )


@dataclass
class _Phase:
    phase_id: str
    resources: WorkspaceResourceRequest


@dataclass
class _Workflow:
    phases: list[_Phase]


def test_start_answers_422_for_a_stored_request_above_the_ceiling() -> None:
    from syn_api.routes.executions.commands import _check_phase_declarations

    stored = _Workflow([_Phase("build", WorkspaceResourceRequest(memory_mb=12288))])

    with pytest.raises(HTTPException) as caught:
        _check_phase_declarations(stored)  # type: ignore[arg-type]

    assert caught.value.status_code == 422
    assert "SYN_WORKSPACE_MEMORY_MAX_MB" in str(caught.value.detail)


def test_the_export_writes_the_request_back_so_a_reinstall_keeps_it() -> None:
    from syn_api.routes.workflows.queries import _yaml_declaration_lines
    from syn_api.types import PhaseDefinitionResponse, PhaseResourcesResponse

    phase = PhaseDefinitionResponse.model_validate(
        {"phase_id": "build", "name": "Build", "order": 1, "agent_type": "claude"}
    )
    declared = phase.model_copy(update={"resources": PhaseResourcesResponse(memory_mb=12288)})

    assert "    resources: {memory_mb: 12288}" in _yaml_declaration_lines(declared)
    assert not any("resources" in line for line in _yaml_declaration_lines(phase))
