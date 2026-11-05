"""A phase's workspace memory and pids requests: declared in YAML, carried, and held to the ceiling (okrs-51p.30)."""

from __future__ import annotations

from types import MappingProxyType

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration import (
    PhaseDefinition,
    WorkflowDefinition,
    WorkspaceMemoryOverCapError,
    WorkspacePidsOverCapError,
    WorkspaceResourceRequest,
    require_memory_within_cap,
    require_phases_within_cap,
    require_pids_within_cap,
    validate_phase_declarations,
)
from syn_domain.contexts.orchestration._shared.workspace_resources import (
    stored_resource_request,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)

pytestmark = pytest.mark.unit

_YAML = """
id: dreamship-build
name: DreamShip build
phases:
  - id: build
    name: Build
    order: 1
    prompt_template: build it
    resources:
      memory_mb: 12288
  - id: review
    name: Review
    order: 2
    prompt_template: review it
"""


class _Template:
    """The two attributes `validate_phase_declarations` reads off a stored template."""

    def __init__(self, *phases: PhaseDefinition) -> None:
        self.phases = list(phases)
        self.skills = ()


def _phase(memory_mb: int | None) -> PhaseDefinition:
    return PhaseDefinition(
        phase_id="build",
        name="Build",
        order=1,
        resources=WorkspaceResourceRequest(memory_mb=memory_mb),
    )


def test_the_yaml_request_reaches_the_domain_phase_and_an_undeclared_phase_gets_none() -> None:
    definition = WorkflowDefinition.from_yaml(_YAML)

    build, review = (p.to_domain() for p in definition.phases)

    assert build.resources.memory_mb == 12288
    assert review.resources.memory_mb is None


@pytest.mark.parametrize(
    "resources",
    [{"memory_mb": 128}, {"memory_mb": 4096, "cpu": 4}, {"memory": 4096}],
    ids=["below-the-floor", "unknown-key-beside", "misspelled-key"],
)
def test_a_malformed_request_is_refused_at_authoring(resources: dict[str, int]) -> None:
    """A misspelled key must not install as "no request" and run in the default."""
    flow = "{" + ", ".join(f"{k}: {v}" for k, v in resources.items()) + "}"
    yaml = _YAML.replace("resources:\n      memory_mb: 12288", f"resources: {flow}")
    assert yaml != _YAML

    with pytest.raises(ValidationError):
        WorkflowDefinition.from_yaml(yaml)


def test_the_effective_memory_is_the_request_or_the_default() -> None:
    assert WorkspaceResourceRequest(memory_mb=8192).memory_mb_or(4096) == 8192
    assert WorkspaceResourceRequest().memory_mb_or(4096) == 4096


def test_a_request_at_the_ceiling_passes_and_one_above_is_refused_by_name() -> None:
    require_memory_within_cap(WorkspaceResourceRequest(memory_mb=16384), 16384, phase_id="build")
    require_memory_within_cap(WorkspaceResourceRequest(), 4096, phase_id="build")

    with pytest.raises(WorkspaceMemoryOverCapError) as caught:
        require_memory_within_cap(
            WorkspaceResourceRequest(memory_mb=16385), 16384, phase_id="build"
        )

    assert (caught.value.requested_mb, caught.value.cap_mb) == (16385, 16384)
    assert "Phase 'build'" in str(caught.value)
    assert "SYN_WORKSPACE_MEMORY_MAX_MB" in str(caught.value)


def test_start_refuses_a_stored_phase_above_the_ceiling() -> None:
    """The start check, which runs before any phase is paid for."""
    stored = _Template(_phase(12288))

    validate_phase_declarations(stored, memory_ceiling_mb=16384)  # type: ignore[arg-type]
    with pytest.raises(WorkspaceMemoryOverCapError):
        validate_phase_declarations(stored, memory_ceiling_mb=8192)  # type: ignore[arg-type]


def test_start_reads_the_deployment_ceiling_when_none_is_passed() -> None:
    """Unset SYN_WORKSPACE_MEMORY_MAX_MB is the default limit, 4096: 12288 is refused."""
    with pytest.raises(WorkspaceMemoryOverCapError):
        validate_phase_declarations(_Template(_phase(12288)))  # type: ignore[arg-type]
    validate_phase_declarations(_Template(_phase(None)))  # type: ignore[arg-type]


def test_a_template_stored_before_the_field_replays_as_no_request() -> None:
    old_event_phase = MappingProxyType({"phase_id": "build", "name": "Build", "order": 1})

    replayed = PhaseDefinition.model_validate(dict(old_event_phase))

    assert replayed.resources == WorkspaceResourceRequest()
    assert stored_resource_request(None) == WorkspaceResourceRequest()
    assert stored_resource_request({"memory_mb": 8192}).memory_mb == 8192


class _Rehydrated:
    """What `_get_executable_phases` reads: real `PhaseDefinition`s, as replay builds them."""

    def __init__(self, *phases: PhaseDefinition) -> None:
        self.phases = list(phases)
        self.claude_plugins = ()
        self.skills = ()


def _bare_handler() -> ExecuteWorkflowHandler:
    handler = ExecuteWorkflowHandler.__new__(ExecuteWorkflowHandler)
    handler._phase_plugin_resolver = None
    handler._phase_skill_resolver = None
    return handler


async def test_the_execution_boundary_pins_the_request_on_the_executable_phase() -> None:
    """Pinned here, the request lands in `WorkflowExecutionStarted.pinned_phases`."""
    (pinned,) = await _bare_handler()._get_executable_phases(
        _Rehydrated(_phase(2048))  # type: ignore[arg-type]
    )

    assert pinned.resources.memory_mb == 2048


async def test_a_direct_handler_caller_is_refused_above_the_ceiling() -> None:
    """`handle()` does not call validate_phase_declarations; its own loop must refuse."""
    with pytest.raises(WorkspaceMemoryOverCapError, match="build"):
        await _bare_handler()._get_executable_phases(
            _Rehydrated(_phase(12288))  # type: ignore[arg-type]
        )


def test_the_workflow_detail_read_model_stores_and_reloads_the_request() -> None:
    """The #1429 seam: a field `from_dict` reads but `to_dict` drops reloads as its default."""
    from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import (
        PhaseDefinitionDetail,
        WorkflowDetail,
    )

    detail = WorkflowDetail(
        id="wf",
        name="wf",
        workflow_type="custom",
        classification="standard",
        description=None,
        phases=[
            PhaseDefinitionDetail(
                id="build", name="Build", resources=WorkspaceResourceRequest(memory_mb=12288)
            )
        ],
    )

    (reloaded,) = WorkflowDetail.from_dict(detail.to_dict()).phases

    assert reloaded.resources.memory_mb == 12288


# -- pids_limit (okrs-51p.30): the same request, for --pids-limit ----------------


def _pids_phase(pids_limit: int | None) -> PhaseDefinition:
    return PhaseDefinition(
        phase_id="build",
        name="Build",
        order=1,
        resources=WorkspaceResourceRequest(pids_limit=pids_limit),
    )


def test_the_yaml_pids_request_reaches_the_domain_phase_beside_memory() -> None:
    yaml = _YAML.replace("memory_mb: 12288", "{memory_mb: 12288, pids_limit: 2048}").replace(
        "resources:\n      {", "resources: {"
    )
    assert "pids_limit: 2048" in yaml

    build, review = (p.to_domain() for p in WorkflowDefinition.from_yaml(yaml).phases)

    assert (build.resources.memory_mb, build.resources.pids_limit) == (12288, 2048)
    assert review.resources.pids_limit is None


def test_a_pids_request_below_the_floor_is_refused_at_authoring() -> None:
    with pytest.raises(ValidationError):
        WorkspaceResourceRequest(pids_limit=63)
    assert WorkspaceResourceRequest(pids_limit=64).pids_limit == 64


def test_the_effective_pids_limit_is_the_request_or_the_default() -> None:
    assert WorkspaceResourceRequest(pids_limit=2048).pids_limit_or(256) == 2048
    assert WorkspaceResourceRequest().pids_limit_or(256) == 256
    assert WorkspaceResourceRequest(memory_mb=8192).pids_limit_or(256) == 256


def test_a_pids_request_at_the_ceiling_passes_and_one_above_is_refused_by_name() -> None:
    require_pids_within_cap(WorkspaceResourceRequest(pids_limit=4096), 4096, phase_id="build")
    require_pids_within_cap(WorkspaceResourceRequest(), 256, phase_id="build")

    with pytest.raises(WorkspacePidsOverCapError) as caught:
        require_pids_within_cap(WorkspaceResourceRequest(pids_limit=4097), 4096, phase_id="build")

    assert (caught.value.requested, caught.value.cap) == (4097, 4096)
    message = str(caught.value)
    assert "Phase 'build'" in message
    assert "SYN_WORKSPACE_PIDS_MAX" in message
    assert "Resource temporarily unavailable" in message


def test_install_and_resume_hold_pids_to_the_ceiling_beside_memory() -> None:
    """`require_phases_within_cap` is what install and resume call."""
    phases = [_pids_phase(2048)]

    require_phases_within_cap(phases, 4096, pids_cap=2048)
    with pytest.raises(WorkspacePidsOverCapError):
        require_phases_within_cap(phases, 4096, pids_cap=1024)


def test_start_refuses_a_stored_pids_request_above_the_ceiling() -> None:
    stored = _Template(_pids_phase(2048))

    validate_phase_declarations(stored, pids_ceiling=4096)  # type: ignore[arg-type]
    with pytest.raises(WorkspacePidsOverCapError):
        validate_phase_declarations(stored, pids_ceiling=1024)  # type: ignore[arg-type]


def test_start_reads_the_deployment_pids_ceiling_when_none_is_passed() -> None:
    """Unset SYN_WORKSPACE_PIDS_MAX is the default limit, 256: 2048 is refused."""
    with pytest.raises(WorkspacePidsOverCapError):
        validate_phase_declarations(_Template(_pids_phase(2048)))  # type: ignore[arg-type]
    validate_phase_declarations(_Template(_pids_phase(256)))  # type: ignore[arg-type]


async def test_a_direct_handler_caller_is_refused_above_the_pids_ceiling() -> None:
    with pytest.raises(WorkspacePidsOverCapError, match="build"):
        await _bare_handler()._get_executable_phases(
            _Rehydrated(_pids_phase(2048))  # type: ignore[arg-type]
        )


async def test_the_execution_boundary_pins_the_pids_request() -> None:
    (pinned,) = await _bare_handler()._get_executable_phases(
        _Rehydrated(_pids_phase(128))  # type: ignore[arg-type]
    )

    assert pinned.resources.pids_limit == 128


def test_a_stored_request_without_pids_replays_as_no_pids_request() -> None:
    assert stored_resource_request({"memory_mb": 8192}).pids_limit is None
    assert stored_resource_request({"pids_limit": 2048}).pids_limit == 2048


def test_the_workflow_detail_read_model_stores_and_reloads_the_pids_request() -> None:
    from syn_domain.contexts.orchestration.domain.read_models.workflow_detail import (
        PhaseDefinitionDetail,
        WorkflowDetail,
    )

    detail = WorkflowDetail(
        id="wf",
        name="wf",
        workflow_type="custom",
        classification="standard",
        description=None,
        phases=[
            PhaseDefinitionDetail(
                id="build",
                name="Build",
                resources=WorkspaceResourceRequest(memory_mb=8192, pids_limit=2048),
            )
        ],
    )

    (reloaded,) = WorkflowDetail.from_dict(detail.to_dict()).phases

    assert reloaded.resources == WorkspaceResourceRequest(memory_mb=8192, pids_limit=2048)
