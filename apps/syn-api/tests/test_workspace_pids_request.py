"""A phase's workspace pids request through the API: install, start, read back, export (okrs-51p.30)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from syn_domain.contexts.orchestration import WorkflowDefinition, WorkspaceResourceRequest

pytestmark = pytest.mark.unit


@pytest.fixture
def _storage():
    """In-memory adapters, as the other service-level workflow tests use."""
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    yield
    reset_storage()
    reset_projection_manager()


@pytest.mark.usefixtures("_storage")
async def test_yaml_install_refuses_a_pids_request_above_the_ceiling_and_stores_nothing() -> None:
    from syn_api.routes.workflows.commands import create_workflow_from_yaml
    from syn_api.routes.workflows.queries import get_workflow
    from syn_api.types import Err

    result = await create_workflow_from_yaml(
        """
id: many-threads
name: Many threads
phases:
  - id: build
    name: Build
    order: 1
    prompt_template: build it
    resources: {pids_limit: 2048}
"""
    )

    assert isinstance(result, Err)
    assert "SYN_WORKSPACE_PIDS_MAX" in str(result.message)
    assert isinstance(await get_workflow("many-threads"), Err)


@pytest.mark.usefixtures("_storage")
async def test_api_create_stores_the_pids_request_and_reads_it_back() -> None:
    from syn_api.routes.workflows import create_workflow
    from syn_api.routes.workflows.queries import get_workflow
    from syn_api.types import Err

    created = await create_workflow(
        name="Threads",
        workflow_id="threads-dicts",
        phases=[
            {
                "phase_id": "build",
                "name": "Build",
                "order": 1,
                "resources": {"memory_mb": 2048, "pids_limit": 128},
            }
        ],
    )
    assert not isinstance(created, Err), created

    detail = await get_workflow("threads-dicts")
    assert not isinstance(detail, Err), detail
    (phase,) = detail.value.phases
    assert (phase.resources.memory_mb, phase.resources.pids_limit) == (2048, 128)


@dataclass
class _Phase:
    phase_id: str
    resources: WorkspaceResourceRequest


@dataclass
class _Workflow:
    phases: list[_Phase]


def test_start_answers_422_for_a_stored_pids_request_above_the_ceiling() -> None:
    from syn_api.routes.executions.commands import _check_phase_declarations

    stored = _Workflow([_Phase("build", WorkspaceResourceRequest(pids_limit=2048))])

    with pytest.raises(HTTPException) as caught:
        _check_phase_declarations(stored)  # type: ignore[arg-type]

    assert caught.value.status_code == 422
    assert "SYN_WORKSPACE_PIDS_MAX" in str(caught.value.detail)


@pytest.mark.parametrize(
    ("resources", "line"),
    [
        ({"pids_limit": 2048}, "    resources: {pids_limit: 2048}"),
        (
            {"memory_mb": 12288, "pids_limit": 2048},
            "    resources: {memory_mb: 12288, pids_limit: 2048}",
        ),
    ],
    ids=["pids-only", "memory-and-pids"],
)
def test_the_export_writes_every_request_back_so_a_reinstall_keeps_it(
    resources: dict[str, int], line: str
) -> None:
    from syn_api.routes.workflows.queries import _yaml_declaration_lines
    from syn_api.types import PhaseDefinitionResponse, PhaseResourcesResponse

    phase = PhaseDefinitionResponse.model_validate(
        {"phase_id": "build", "name": "Build", "order": 1, "agent_type": "claude"}
    )
    declared = phase.model_copy(update={"resources": PhaseResourcesResponse(**resources)})

    lines = _yaml_declaration_lines(declared)
    assert line in lines

    # And it reads back as the request it was: the export/reinstall round trip.
    yaml = "id: rt\nname: rt\nphases:\n  - id: build\n    name: Build\n    order: 1\n"
    (reread,) = WorkflowDefinition.from_yaml(yaml + line + "\n").phases
    assert reread.resources == WorkspaceResourceRequest(**resources)
