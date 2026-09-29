"""Reading facts back off replayed events.

An aggregate rehydrates from whatever the store hands back, and that is not
always the typed event class it wrote. Under ADR-023 the store falls back to
`GenericDomainEvent` when a stored payload fails typed validation, so every
read of a field during replay has to work on both shapes. These two helpers are
that seam, kept together and out of the aggregate because they are about event
PAYLOADS, not about any decision the aggregate makes.

`evt` in particular is why a replayed field is never load-bearing for a rule
that must fail closed: it returns the default for a field it cannot find, so a
rule keyed on one would silently open on exactly the stream that lost it. See
`resume_rules.refuse_resume` for the case that taught us.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    PhaseDefinition,
)

if TYPE_CHECKING:
    from event_sourcing import DomainEvent


def evt(event: DomainEvent, field: str, default: Any = None) -> Any:  # noqa: ANN401
    """Get field from event, handling both typed and GenericDomainEvent formats.

    Returns Any because the caller knows the concrete type based on the field
    name.
    """
    if hasattr(event, field):
        return getattr(event, field)
    data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
    return data.get(field, default)


logger = logging.getLogger(__name__)


class PhaseDefinitionPayload(BaseModel):
    """One phase as a replayed `WorkflowExecutionStarted` carries it.

    A MODEL rather than `dict[str, Any]` so the four fields this code reads are
    named once and checked once, instead of being indexed by string at the point
    of use where a missing key is a KeyError during replay (#1268).

    `extra="allow"` on purpose: old streams carry keys this model does not name,
    and replay must not fail because a payload knows more than we do. What it
    must not do is silently accept a payload MISSING what sequencing needs -
    hence no defaults on the first three.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    phase_id: str
    name: str
    order: int
    timeout_seconds: int = 300


_PHASE_DEFINITIONS = TypeAdapter(list[PhaseDefinitionPayload])


def parse_phase_definitions(raw_defs: object) -> list[PhaseDefinition]:
    """The replayed phase definitions, sorted, or empty when unreadable.

    Sorted by `order`, which `WorkflowDefinition.from_yaml` guarantees is unique
    per phase - so this is a total order, and consumers that walk phases in
    sequence (notably `resume_rules.completed_prefix`) may rely on it. Nothing
    re-checks that here; #1455 tracks it.

    Unreadable is EMPTY, not an exception, matching `read_pinned_phases`: a
    payload this cannot validate would otherwise make the execution unloadable,
    and an execution that cannot be loaded cannot be inspected, cancelled or
    resumed. Empty means the aggregate does not sequence, which is the documented
    behaviour when `phase_definitions` is absent anyway.
    """
    if not raw_defs:
        return []
    try:
        parsed = _PHASE_DEFINITIONS.validate_python(raw_defs)
    except ValidationError:
        logger.warning("Unreadable phase_definitions on a replayed start event; treating as absent")
        return []
    return sorted(
        [
            PhaseDefinition(
                phase_id=d.phase_id,
                name=d.name,
                order=d.order,
                timeout_seconds=d.timeout_seconds,
            )
            for d in parsed
        ],
        key=lambda p: p.order,
    )
