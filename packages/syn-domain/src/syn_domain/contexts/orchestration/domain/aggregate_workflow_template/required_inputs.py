"""Which inputs a stored workflow requires at admission (PC-66).

The explicit ``inputs:`` declarations are the primary source. A definition
installed before it declared ``task`` still substitutes the task into its
prompts, though, and the event store keeps that definition exactly as it was
installed: a declaration added to the YAML later never reaches it without a
reinstall. So a workflow that declares nothing about ``task`` but whose prompts
reference it requires one all the same. A workflow whose prompts never mention
the task does not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    InputDeclaration,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    TASK_INPUT_KEY,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
    )

#: The placeholder a phase prompt writes for the dispatched task. Prompt
#: rendering substitutes it, and so does ``{{task}}`` as an ordinary input.
TASK_PLACEHOLDER = "$ARGUMENTS"

_TASK_REFERENCES = (TASK_PLACEHOLDER, f"{{{{{TASK_INPUT_KEY}}}}}")


def required_input_declarations(
    declared: Sequence[InputDeclaration],
    phases: Sequence[PhaseDefinition],
) -> list[InputDeclaration]:
    """The declarations admission enforces: ``declared``, plus ``task`` where implied."""
    if any(decl.name == TASK_INPUT_KEY for decl in declared):
        return list(declared)
    if not any(
        ref in (phase.prompt_template or "") for phase in phases for ref in _TASK_REFERENCES
    ):
        return list(declared)
    return [
        *declared,
        InputDeclaration(
            name=TASK_INPUT_KEY,
            description="Implied: a phase prompt references the task",
            required=True,
        ),
    ]
