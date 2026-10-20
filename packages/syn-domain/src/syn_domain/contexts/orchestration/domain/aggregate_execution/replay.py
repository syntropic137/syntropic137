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

from syn_domain.contexts.orchestration._shared.phase_order import phase_order_conflict
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


def _read_payloads(raw_defs: object) -> list[PhaseDefinitionPayload]:
    if not raw_defs:
        return []
    try:
        return _PHASE_DEFINITIONS.validate_python(raw_defs)
    except ValidationError:
        logger.warning("Unreadable phase_definitions on a replayed start event; treating as absent")
        return []


def replay_phases(raw_defs: object) -> tuple[list[PhaseDefinition], str | None]:
    """The sequenced phases of a replayed start, and why they are empty if they conflict.

    `parse_phase_definitions` answers a conflict with an empty list so the
    execution stays loadable, inspectable and cancellable (#1455). That empty
    list is indistinguishable from "this start never carried phases", which the
    processor reads as nothing left to run. The reason is kept beside it so the
    aggregate can refuse to COMPLETE such a run instead of recording success
    over phases that never ran. Absent or unreadable payloads carry no reason:
    they are the documented legacy "does not sequence" case.
    """
    return parse_phase_definitions(raw_defs), phase_definitions_conflict(raw_defs)


def phase_definitions_conflict(raw_defs: object) -> str | None:
    """Why a start's raw `phase_definitions` are not a total order, or None.

    The one reading of that payload for every consumer that sequences from it:
    the aggregate's replay above, and the to-do projection, which must queue no
    phase from a list the aggregate refuses to sequence (#1455).
    """
    return phase_order_conflict(_read_payloads(raw_defs))


def refuse_unordered(conflict: str | None, verb: str) -> None:
    """Nothing was sequenced, so no phase may start and "no pending phase" is not "all done".

    Starting a phase is refused as well as completing the execution: a to-do
    record written before the projection refused such a list can still hold a
    pending phase, and the aggregate is what stops it running.
    """
    if conflict is not None:
        msg = f"Cannot {verb} an execution whose phases are unordered: {conflict}"
        raise ValueError(msg)


def parse_phase_definitions(raw_defs: object) -> list[PhaseDefinition]:
    """The replayed phase definitions, sorted, or empty when unreadable.

    Sorted by `order`, and only ever a TOTAL order: a payload that repeats a
    phase id or shares an order between two phases is refused here (#1455),
    because every consumer that walks phases in sequence -
    `resume_rules.completed_prefix`, `review_rounds.next_phase` - would
    otherwise decide by payload order, or skip a tied phase without a word.
    The start command refuses to write such a payload, but this is the
    boundary that reads it, and a stream can predate that check.

    Unreadable is EMPTY, not an exception, matching `read_pinned_phases`: a
    payload this cannot validate would otherwise make the execution unloadable,
    and an execution that cannot be loaded cannot be inspected, cancelled or
    resumed. Empty means the aggregate does not sequence, which is the documented
    behaviour when `phase_definitions` is absent anyway. A tie is unreadable in
    exactly that sense - there is no order to sequence by - so it is refused the
    same way rather than by raising during replay.
    """
    parsed = _read_payloads(raw_defs)
    if not parsed:
        return []
    conflict = phase_order_conflict(parsed)
    if conflict is not None:
        logger.warning(
            "phase_definitions on a replayed start event are not a total order (%s); "
            "treating as absent (#1455)",
            conflict,
        )
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
