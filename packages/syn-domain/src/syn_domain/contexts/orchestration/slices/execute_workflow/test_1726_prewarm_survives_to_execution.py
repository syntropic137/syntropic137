"""`prewarm` has to reach provisioning, not merely be written (#1726).

It travels the same hops as `delivers_repo_changes` (#1308): the YAML, the
template's created event, the event store as JSON, the rehydrated aggregate,
a phase edit, and `ExecutablePhase`. Its default is False, so a hop that drops
it is silent - the phase provisions without installing, and its offline agent
fails every gate on a missing dependency. The fixtures are the SHIPPED eval
workflows, because those are the phases the A/B needs warm.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from syn_domain.contexts.orchestration._shared.workflow_definition import (
    PhaseYamlDefinition,
    WorkflowDefinition,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowPhaseUpdatedEvent import (
    WorkflowPhaseUpdatedEvent,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.test_1308_the_declaration_survives_to_execution import (
    _executable_phases,  # pyright: ignore[reportPrivateUsage]
)

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_WORKFLOWS = Path(__file__).resolve().parents[8] / "workflows"

_WARM = ["evals/verify-pinned-sdlc-baseline", "evals/verify-pinned-sdlc-lean"]
#: The other verifiers in the same suite keep the default, so their scores stay
#: the experiments they were.
_COLD = ["evals/verify-pinned", "evals/verify-pinned-codex", "sdlc/implement-v3"]


@pytest.mark.parametrize("workflow", _WARM)
async def test_the_sdlc_eval_phase_reaches_execution_prewarmed(workflow: str) -> None:
    phases = await _executable_phases(_WORKFLOWS / workflow / "workflow.yaml")

    assert phases["verify"].prewarm is True
    assert phases["verify"].clone_repos is True


@pytest.mark.parametrize("workflow", _COLD)
async def test_a_phase_that_does_not_declare_it_is_not_prewarmed(workflow: str) -> None:
    phases = await _executable_phases(_WORKFLOWS / workflow / "workflow.yaml")

    assert phases and all(p.prewarm is False for p in phases.values())


async def test_an_edit_to_the_phase_leaves_prewarm_declared() -> None:
    workflow = _WORKFLOWS / "evals/verify-pinned-sdlc-lean/workflow.yaml"
    edited = await _executable_phases(
        workflow,
        then=[
            WorkflowPhaseUpdatedEvent(
                workflow_id=WorkflowDefinition.from_file(workflow).id,
                phase_id="verify",
                prompt_template="Edited.",
            )
        ],
    )

    assert edited["verify"].prompt_template == "Edited."
    assert edited["verify"].prewarm is True


def test_prewarm_without_a_checkout_is_refused_at_authoring() -> None:
    with pytest.raises(ValidationError, match="prewarm installs into the checkout"):
        PhaseYamlDefinition(
            id="p", name="P", order=1, prompt_template="x", clone_repos=False, prewarm=True
        )
