"""A workflow template refuses phases that are not a total order (#1455).

`WorkflowDefinition.from_yaml` used to be the only check, and `POST /workflows`
never goes through it: it builds the phases itself and hands them to this
aggregate. So the aggregate that owns the template is where the invariant has
to hold, for a fresh create and for an install that replaces the definition.
"""

from __future__ import annotations

import pytest

from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    WorkflowClassification,
    WorkflowType,
)
from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
    CreateWorkflowTemplateCommand,
)
from syn_domain.contexts.orchestration.domain.commands.UpdateWorkflowTemplateCommand import (
    UpdateWorkflowTemplateCommand,
)

pytestmark = pytest.mark.unit

WORKFLOW = "wf-phase-order"

NOT_A_TOTAL_ORDER = pytest.mark.parametrize(
    ("phases", "refusal"),
    [
        ([("B", 1), ("A", 1)], "Phase orders must be unique.*: 1"),
        ([("A", 1), ("B", 1)], "Phase orders must be unique.*: 1"),
        ([("A", 1), ("A", 2)], "Phase IDs must be unique.*: A"),
    ],
    ids=["tied-orders-B-first", "tied-orders-A-first", "duplicate-phase-ids"],
)


def _phases(phases: list[tuple[str, int]]) -> list[PhaseDefinition]:
    return [PhaseDefinition(phase_id=p, name=p, order=order) for p, order in phases]


def _create(phases: list[tuple[str, int]]) -> CreateWorkflowTemplateCommand:
    return CreateWorkflowTemplateCommand(
        aggregate_id=WORKFLOW,
        name="Phase order",
        workflow_type=WorkflowType.RESEARCH,
        classification=WorkflowClassification.SIMPLE,
        phases=_phases(phases),
    )


@NOT_A_TOTAL_ORDER
def test_create_refuses(phases: list[tuple[str, int]], refusal: str) -> None:
    aggregate = WorkflowTemplateAggregate()

    with pytest.raises(ValueError, match=refusal):
        aggregate.create_workflow(_create(phases))

    assert aggregate.get_uncommitted_events() == []


@NOT_A_TOTAL_ORDER
def test_update_refuses(phases: list[tuple[str, int]], refusal: str) -> None:
    aggregate = WorkflowTemplateAggregate()
    aggregate.create_workflow(_create([("A", 1), ("B", 2)]))
    aggregate.mark_events_as_committed()

    with pytest.raises(ValueError, match=refusal):
        aggregate.update_workflow(
            UpdateWorkflowTemplateCommand(
                aggregate_id=WORKFLOW,
                name="Phase order",
                workflow_type=WorkflowType.RESEARCH,
                classification=WorkflowClassification.SIMPLE,
                phases=_phases(phases),
            )
        )

    assert aggregate.get_uncommitted_events() == []
    assert [(p.phase_id, p.order) for p in aggregate.phases] == [("A", 1), ("B", 2)]
