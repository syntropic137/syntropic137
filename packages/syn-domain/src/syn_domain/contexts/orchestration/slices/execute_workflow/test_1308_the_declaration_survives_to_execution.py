"""`delivers_repo_changes` has to reach the gate, not merely be written (#1308).

The unpushed-work gate now asks the phase whether a change to the repositories
is part of what it delivers, because `git status` cannot tell an agent's edit
from a `Cargo.lock` that `cargo check` rewrote while inspecting the toolchain.
That question is only worth asking if the answer arrives.

IT TRAVELS SIX HOPS, and every one of them has a default that hides a drop:
`PhaseYamlDefinition` -> `PhaseDefinition` -> `WorkflowTemplateCreated` -> the
event store -> `WorkflowTemplateAggregate` -> `ExecutablePhase`. Each defaults
to True, which is the STRICT reading, so a hop that loses the value produces
exactly the incident it was added to fix - a reporting phase failed for its own
build tool's churn - while both ends of that hop still look right.

The serialization hop is the one that cannot be seen any other way. A field the
event does not carry is lost on the RESTART path only: the phases are correct
for as long as the API stays up, and wrong the next time it comes back. So the
round trip below is through `model_dump(mode="json")` and back, which is what
the event store holds.

The fixtures are THE SHIPPED WORKFLOWS, not a constructed one. What has to be
true is that this repository's own bootstrap, premise, verify and review phases
reach execution declaring False - a synthetic workflow would prove the plumbing
while leaving every real phase still failing on a lockfile.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration._shared.workflow_definition import WorkflowDefinition
from syn_domain.contexts.orchestration._shared.yaml_to_command import (
    build_command_from_definition,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
    ExecuteWorkflowCommand,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowPhaseUpdatedEvent import (
    WorkflowPhaseUpdatedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import DomainEvent

    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_WORKFLOWS = Path(__file__).resolve().parents[8] / "workflows"


async def _executable_phases(
    workflow: Path, *, then: Sequence[DomainEvent] = ()
) -> dict[str, ExecutablePhase]:
    """The phases production would run, through a real event round trip.

    `then` is the rest of the stream: events recorded against this workflow
    after it was created, replayed in order onto the same fresh aggregate.
    """
    definition = WorkflowDefinition.from_file(workflow)
    origin = WorkflowTemplateAggregate()
    origin.create_workflow(build_command_from_definition(definition))
    (envelope,) = origin.get_uncommitted_events()
    created = envelope.event
    # THE RESTART PATH. Phases come back out of the event store as plain JSON,
    # so a field the event does not carry survives every in-process test and
    # nothing else.
    rehydrated = WorkflowTemplateAggregate()
    for event in (created, *then):
        rehydrated.apply_event(type(event).model_validate(event.model_dump(mode="json")))

    captured: list[ExecutablePhase] = []

    class _Processor:
        async def run(
            self,
            *,
            workflow_id: str,
            workflow_name: str,
            phases: list[ExecutablePhase],
            inputs: dict[str, str],
            execution_id: str,
            repos: list[RepositoryRef],
            admitted: object = None,
        ) -> WorkflowExecutionResult:
            del workflow_name, inputs, repos, admitted
            captured.extend(phases)
            return WorkflowExecutionResult(
                workflow_id=workflow_id,
                execution_id=execution_id,
                status="completed",
                started_at=datetime.now(UTC),
            )

    class _Repo:
        async def get_by_id(self, aggregate_id: str) -> WorkflowTemplateAggregate | None:
            return rehydrated if aggregate_id == definition.id else None

    handler = ExecuteWorkflowHandler(
        processor=_Processor(),  # type: ignore[arg-type]
        workflow_repository=_Repo(),  # type: ignore[arg-type]
    )
    await handler.handle(ExecuteWorkflowCommand(aggregate_id=definition.id))
    return {p.phase_id: p for p in captured}


#: (workflow, phase id) for every phase in this repository whose deliverable is
#: a report. Each must reach execution declaring False.
#:
#: NOT THE DEFAULT, which is what makes the list worth having: False is the only
#: value no dropped hop can produce, so each entry fails if the declaration is
#: lost anywhere between the YAML and `ExecutablePhase`.
_REPORTING = [
    ("sdlc/implement", "bootstrap"),
    ("sdlc/implement", "verify"),
    ("sdlc/implement", "open_pr"),
    ("sdlc/implement-v2", "premise"),
    ("sdlc/implement-v2", "verify"),
    ("sdlc/implement-v2", "open_pr"),
    ("sdlc/pr-review", "investigate"),
    ("sdlc/pr-review", "verify"),
    ("sdlc/pr-review", "report"),
    ("sdlc/pr-review-slp", "investigate"),
    ("sdlc/pr-review-slp", "verify"),
    ("sdlc/pr-review-slp", "report"),
    ("sdlc/refactor-plan", "coverage-gate"),
    ("sdlc/refactor-plan", "characterize"),
    ("sdlc/refactor-plan", "seams"),
    ("sdlc/refactor-plan", "cross-model-review"),
    ("sdlc/refactor-plan", "revise"),
    ("sdlc/research-plan", "research"),
    ("sdlc/research-plan", "plan"),
    ("sdlc/research-plan", "cross-model-review"),
    ("sdlc/research-plan", "revise"),
    ("custom/bake-sonnet", "bootstrap"),
    ("custom/bake-sonnet", "verify"),
    ("custom/bake-sonnet", "open_pr"),
]

#: The phases that DO own a branch. Listed for the same reason the gate keeps
#: `test_b`: a change that made every phase report False would satisfy the list
#: above while switching #1184 off for the only two phases that commit.
_OWNS_A_BRANCH = [
    ("sdlc/implement", "implement"),
    ("sdlc/implement-v2", "implement"),
    ("sdlc/quickfix", "quickfix"),
    ("custom/bake-sonnet", "implement"),
]


@pytest.mark.parametrize(("workflow", "phase_id"), _REPORTING)
async def test_a_reporting_phase_reaches_execution_declaring_no_repo_changes(
    workflow: str, phase_id: str
) -> None:
    """Its own tooling dirtying the tree must not fail it (#1308)."""
    phases = await _executable_phases(_WORKFLOWS / workflow / "workflow.yaml")

    assert phase_id in phases, f"{workflow} no longer has a '{phase_id}' phase"
    assert phases[phase_id].delivers_repo_changes is False


@pytest.mark.parametrize(("workflow", "phase_id"), _OWNS_A_BRANCH)
async def test_a_phase_that_commits_still_reaches_execution_judged_strictly(
    workflow: str, phase_id: str
) -> None:
    """The gate #1184 built must still be armed where work is actually made."""
    phases = await _executable_phases(_WORKFLOWS / workflow / "workflow.yaml")

    assert phase_id in phases, f"{workflow} no longer has a '{phase_id}' phase"
    assert phases[phase_id].delivers_repo_changes is True


async def test_an_edit_to_a_phase_leaves_its_declaration_where_the_author_put_it() -> None:
    """A field the edit never mentions must arrive unchanged (#1308).

    THE SEVENTH HOP, and the only one that is not on the startup path: a
    workflow is not only created, it is edited, and the edit is an event in
    the same stream. `WorkflowPhaseUpdated` carries a prompt and four optional
    overrides - it has never carried `delivers_repo_changes` and should not,
    because the declaration belongs to the workflow author in the YAML. What
    it must not do is RESET it, which is what applying the event by rebuilding
    the phase from its named fields did: `bootstrap` came back True, the gate
    came back on, and the next lockfile failed the phase again.

    The edit here changes only the prompt, which is the ordinary case and the
    one that hid it, and the assertion is on the `ExecutablePhase` the
    processor hands to the gate rather than on the aggregate's own phase - the
    value has to survive the remaining hops too, and this is the hop that
    drops things.
    """
    workflow = _WORKFLOWS / "sdlc/implement/workflow.yaml"
    edited = await _executable_phases(
        workflow,
        then=[
            WorkflowPhaseUpdatedEvent(
                workflow_id=WorkflowDefinition.from_file(workflow).id,
                phase_id="bootstrap",
                prompt_template="Edited: check the toolchain and stop.",
            )
        ],
    )

    assert edited["bootstrap"].prompt_template == "Edited: check the toolchain and stop."
    assert edited["bootstrap"].delivers_repo_changes is False
    # The edit is to one phase. Its neighbours are not collateral.
    assert edited["implement"].delivers_repo_changes is True
    assert edited["verify"].delivers_repo_changes is False
