"""A resume is held to TODAY's workspace memory ceiling before it is admitted (okrs-51p.30).

Codex on #2148: the parent's pinned requests were admitted under the ceiling
of its own start. After an operator lowers it, a resume was admitted anyway and
refused only at the over-ceiling phase's workspace: the parent's single resume
spent, and the phases before it run and paid for first. The endpoint now answers
422 before saving, and the dispatcher's `validate` refuses before spawning.

The deployment ceiling here is the unset default, 4096. An inherited phase that
asked for more is not held to it: the child does not run it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException
from test_resume_endpoint import (  # pyright: ignore[reportMissingImports]
    PARENT,
    PHASES,
    _Executions,
    _point_wiring_at,
)

from syn_api.routes.executions.resume import ResumeRequest, resume
from syn_domain.contexts.orchestration import WorkspaceMemoryOverCapError, WorkspaceResourceRequest
from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    CompletePhaseCommand,
    FailExecutionCommand,
    StartExecutionCommand,
    StartPhaseCommand,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
    FailureClassification,
    PhaseDefinition,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)
from syn_domain.contexts.orchestration.slices.start_resume.StartResumeHandler import (
    StartResumeHandler,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit


def _parent(requests: Mapping[str, int]) -> WorkflowExecutionAggregate:
    """Completed `research`, failed before `plan`: a resume runs `plan` and `implement`."""
    aggregate = WorkflowExecutionAggregate()
    aggregate.start_execution(
        StartExecutionCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            workflow_name="Resume Me",
            total_phases=len(PHASES),
            inputs={"task": "t"},
            phase_definitions=[
                PhaseDefinition(phase_id=p, name=p.title(), order=i + 1)
                for i, p in enumerate(PHASES)
            ],
            pinned_phases=[
                ExecutablePhase(
                    phase_id=p,
                    name=p.title(),
                    order=i + 1,
                    agent_config=AgentConfiguration(),
                    prompt_template=f"{p} as pinned",
                    resources=WorkspaceResourceRequest(memory_mb=requests.get(p)),
                )
                for i, p in enumerate(PHASES)
            ],
        )
    )
    aggregate.start_phase(
        StartPhaseCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            phase_id="research",
            phase_name="Research",
            phase_order=1,
        )
    )
    aggregate.complete_phase(
        CompletePhaseCommand(
            execution_id=PARENT,
            workflow_id="wf-1",
            phase_id="research",
            session_id=None,
            artifact_id="art-research",
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=0,
            duration_seconds=1.0,
        )
    )
    aggregate.fail_execution(
        FailExecutionCommand(
            execution_id=PARENT,
            error="the harness died",
            error_type="AgentError",
            failed_phase_id="plan",
            completed_phases=1,
            total_phases=len(PHASES),
            classification=FailureClassification.UNCLASSIFIED,
        )
    )
    aggregate.mark_events_as_committed()
    return aggregate


async def test_a_remaining_phase_above_todays_ceiling_is_a_422_and_spends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executions = _Executions(_parent({"implement": 12288}))
    _point_wiring_at(executions, monkeypatch)

    with pytest.raises(HTTPException) as caught:
        await resume(PARENT, ResumeRequest())

    assert caught.value.status_code == 422
    assert "implement" in str(caught.value.detail)
    assert executions.saved == [], "the parent's one resume must not be spent"


async def test_an_inherited_phase_above_the_ceiling_does_not_block_the_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executions = _Executions(_parent({"research": 12288, "plan": 2048}))
    _point_wiring_at(executions, monkeypatch)

    response = await resume(PARENT, ResumeRequest())

    assert response.resume_phase_id == "plan"
    assert executions.saved == [PARENT]


async def test_the_dispatcher_refuses_before_it_spawns_the_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The resume to-do path: `validate` runs before the start is a background task."""
    executions = _Executions(_parent({"plan": 2048}))
    _point_wiring_at(executions, monkeypatch)
    await resume(PARENT, ResumeRequest())  # admitted under today's ceiling

    handler = StartResumeHandler.__new__(StartResumeHandler)
    handler._executions = executions  # type: ignore[assignment]
    monkeypatch.setenv("SYN_WORKSPACE_MEMORY_LIMIT_MB", "1024")
    from syn_shared.settings import reset_settings

    reset_settings()
    try:
        with pytest.raises(WorkspaceMemoryOverCapError, match="plan"):
            await handler.validate(PARENT)
    finally:
        monkeypatch.delenv("SYN_WORKSPACE_MEMORY_LIMIT_MB")
        reset_settings()
