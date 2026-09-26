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
`fork_rules.refuse_fork` for the case that taught us.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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


def parse_phase_definitions(raw_defs: list[dict[str, Any]]) -> list[PhaseDefinition]:
    """Parse raw phase definition dicts into sorted PhaseDefinition objects.

    Sorted by `order`, which `WorkflowDefinition.from_yaml` guarantees is unique
    per phase - so this is a total order, and consumers that walk phases in
    sequence (notably `fork_rules.completed_prefix`) may rely on it. Nothing
    re-checks that here; #1455 tracks it.
    """
    return sorted(
        [
            PhaseDefinition(
                phase_id=d["phase_id"],
                name=d["name"],
                order=d["order"],
                timeout_seconds=d.get("timeout_seconds", 300),
            )
            for d in raw_defs
        ],
        key=lambda p: p.order,
    )
