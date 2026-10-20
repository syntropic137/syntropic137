"""Phase order is a total order: one entry per phase id, one phase per order.

Everything that walks a workflow's phases in sequence depends on it -
`review_rounds.next_phase` advances by `order > completed`, so a phase tied
with the one that just completed is skipped without a word, and
`resume_rules.completed_prefix` decides what a resume inherits by walking the
list until the first gap, so a tie makes that decision depend on payload order
(#1455). Neither can recover from a tie, so the invariant is held here, once,
and checked by every boundary a phase list crosses: the template it is defined
on, the start event it is pinned into, and the replay that reads it back.
`WorkflowDefinition.from_yaml` was its only guardian, and `POST /workflows`
never goes through it.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable


class OrderedPhase(Protocol):
    """Anything that names a phase and its place in the sequence."""

    @property
    def phase_id(self) -> str: ...

    @property
    def order(self) -> int: ...


def phase_order_conflict(phases: Iterable[OrderedPhase]) -> str | None:
    """Why these phases do not form a total order, or None when they do."""
    listed = list(phases)
    repeated_ids = _repeated(p.phase_id for p in listed)
    if repeated_ids:
        return f"Phase IDs must be unique within a workflow; repeated: {', '.join(repeated_ids)}"
    repeated_orders = _repeated(p.order for p in listed)
    if repeated_orders:
        return (
            "Phase orders must be unique within a workflow; shared by more than one "
            f"phase: {', '.join(map(str, repeated_orders))}"
        )
    return None


def _repeated[T: (str, int)](values: Iterable[T]) -> list[T]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def refuse_phase_order_conflict(phases: Iterable[OrderedPhase]) -> None:
    """Raise `ValueError` naming the conflict, for a writer that must not record a tie."""
    conflict = phase_order_conflict(phases)
    if conflict is not None:
        raise ValueError(conflict)
