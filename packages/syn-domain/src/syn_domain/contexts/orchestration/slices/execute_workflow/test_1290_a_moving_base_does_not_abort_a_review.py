"""A review is pinned to its head, and `origin/main` moving does not abort it (#1290).

exec-9819ef91729e reviewed PR #1244 at head `ba307b7a`. PR #1287 merged while it
ran, `origin/main` went from `492ac8f6` to `c8a67374`, and the `verify` phase
halted at its ref-integrity gate. The head had not moved - `verify` re-fetched
and confirmed it. $10.09 bought no verdict.

The gate was right to exist and wrong in what it compared. It ran
``git rev-parse origin/main origin/<pr-branch>`` as ONE assertion against the
recorded SHAs, so either ref moving halted the run - and on a repository where a
queue merges to main, the base moving is the normal condition. That made reviews
and merges mutually exclusive, which is to say the failure rate rose with exactly
the concurrency the platform exists to provide.

WHY THE ASSERTION IS ABOUT THE GATE LINE AND NOT ABOUT THE PROSE. A prompt only
has text, so any test of one is a test of strings; the question is whether it
pins the part that decides behaviour. `_recorded_sha_gates` finds the lines that
oblige the phase to compare a ref against a previously recorded SHA - the defect
was entirely in WHICH refs one of those lines named. So this fails in both wrong
directions: naming `origin/main` there again is the original bug, and dropping
the gate altogether is the over-correction that lets a review certify a head
nobody read.

WHY IT GOES THROUGH EXECUTION AND NOT `Path.read_text`. The prompt travels
`prompt_file` -> `prompt_template` -> `CreateWorkflowTemplateCommand` ->
`WorkflowTemplateCreated` -> JSON in the event store -> `WorkflowTemplateAggregate`
-> `ExecutablePhase`. Reading the .md file would prove the file, and the file is
not what the agent is handed.

WHY BOTH WORKFLOWS. `pr-review-slp` keeps byte-identical copies of `verify.md`
and `report.md` and says so in its own YAML. Nothing mechanically forces them to
agree, so a fix applied to one arm is the drift this repository has been bitten
by before. Parametrising is what makes a half-fix red.
"""

from __future__ import annotations

import re
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
from syn_domain.contexts.orchestration.slices.execute_workflow.ExecuteWorkflowHandler import (
    ExecuteWorkflowHandler,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.processor_types import (
    WorkflowExecutionResult,
)

if TYPE_CHECKING:
    from syn_domain.contexts._shared.repository_ref import RepositoryRef
    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        ExecutablePhase,
    )

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_WORKFLOWS = Path(__file__).resolve().parents[8] / "workflows"

#: Every workflow in this repository that reviews a pull request.
_REVIEW_WORKFLOWS = ["sdlc/pr-review", "sdlc/pr-review-slp"]

#: A line that obliges the phase to compare a ref against a SHA an earlier phase
#: recorded. The defect was which refs one of these named, so these lines are
#: what the test is about.
_RECORDED_SHA_GATE = re.compile(r"must (?:equal|match) the recorded", re.IGNORECASE)

#: Fenced blocks the report phase gives as the literal shape of a verdict line.
_TEXT_BLOCK = re.compile(r"^```text\n(.*?)^```", re.MULTILINE | re.DOTALL)


async def _prompt_reaching_execution(workflow: str, phase_id: str) -> str:
    """The prompt the agent is handed, through the round trip production uses."""
    definition = WorkflowDefinition.from_file(_WORKFLOWS / workflow / "workflow.yaml")
    origin = WorkflowTemplateAggregate()
    origin.create_workflow(build_command_from_definition(definition))
    (envelope,) = origin.get_uncommitted_events()
    created = envelope.event
    # THE RESTART PATH: phases come back out of the store as plain JSON, so a
    # hop that loses the prompt survives every in-process test and nothing else.
    rehydrated = WorkflowTemplateAggregate()
    rehydrated.apply_event(type(created).model_validate(created.model_dump(mode="json")))

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
        ) -> WorkflowExecutionResult:
            del workflow_name, inputs, repos
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

    by_id = {p.phase_id: p for p in captured}
    assert phase_id in by_id, f"{workflow} no longer has a '{phase_id}' phase"
    return by_id[phase_id].prompt_template


def _recorded_sha_gates(prompt: str) -> list[str]:
    return [line for line in prompt.splitlines() if _RECORDED_SHA_GATE.search(line)]


@pytest.mark.parametrize("workflow", _REVIEW_WORKFLOWS)
async def test_the_review_still_gates_on_something(workflow: str) -> None:
    """Letting the base move must not become letting anything move.

    The guarantee worth keeping is that the phase reviews the head it was given.
    A prompt with no recorded-SHA obligation at all would pass the test below
    while certifying code nobody looked at.
    """
    prompt = await _prompt_reaching_execution(workflow, "verify")

    assert _recorded_sha_gates(prompt), (
        f"{workflow} 'verify' no longer asserts any ref against a recorded SHA. "
        "Base movement is survivable; head movement is not."
    )


@pytest.mark.parametrize("workflow", _REVIEW_WORKFLOWS)
async def test_the_base_is_not_what_the_review_is_gated_on(workflow: str) -> None:
    """#1290 itself: no recorded-SHA obligation may name `origin/main`."""
    prompt = await _prompt_reaching_execution(workflow, "verify")

    named_base = [line for line in _recorded_sha_gates(prompt) if "origin/main" in line]

    assert not named_base, (
        f"{workflow} 'verify' gates a recorded SHA on `origin/main`: {named_base}. "
        "An unrelated merge landing on main does not change the PR head, so this "
        "aborts finished work for a reason that is not about the code under review."
    )


@pytest.mark.parametrize("workflow", _REVIEW_WORKFLOWS)
async def test_the_verdict_names_the_base_it_judged(workflow: str) -> None:
    """Continuing past a moved base is only honest if the verdict says which base.

    The report phase gives the verdict line as a literal block. Before #1290 that
    block named the head alone, which is exactly the silent stale-merge-base the
    issue warns about in the other direction: a reader cannot tell a live
    conflict finding from one made against a base that has since moved.
    """
    prompt = await _prompt_reaching_execution(workflow, "report")

    blocks = _TEXT_BLOCK.findall(prompt)
    assert blocks, f"{workflow} 'report' states no literal verdict line"

    naming_both = [b for b in blocks if "head" in b and "base" in b]

    assert naming_both, (
        f"{workflow} 'report' never requires the verdict to name the base it was "
        f"judged against. Literal blocks found: {blocks!r}"
    )
