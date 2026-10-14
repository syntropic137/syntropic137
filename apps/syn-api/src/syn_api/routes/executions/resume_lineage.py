"""Resume lineage as an execution page shows it (#1881).

The read models hold one hop each way: a child's `resumed_from` and a parent's
`resumed_as`. A page also needs the END of the chain, because a failed run
resumed twice (A -> B -> C) should point at C, the run that is still going or
that finished. A parent is resumed at most once, so the chain is a linked list
and following `resumed_as` reaches exactly one leaf.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from syn_api.types import ResumedFromInfo

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_domain.contexts.orchestration.domain.read_models.resume_lineage import ResumedFrom
    from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_detail import (
        WorkflowExecutionDetail,
    )

    DetailById = Callable[[str], Awaitable[WorkflowExecutionDetail | None]]


def resumed_from_info(origin: ResumedFrom | None) -> ResumedFromInfo | None:
    """The read model's origin as the API states it."""
    if origin is None:
        return None
    return ResumedFromInfo(
        parent_execution_id=origin.parent_execution_id, resume_phase_id=origin.resume_phase_id
    )


@dataclass(frozen=True)
class ResumeLineage:
    """Both directions of one execution's resume lineage, ready to serve."""

    resumed_from: ResumedFromInfo | None
    resumed_as: str | None
    latest_resumed_as: str | None
    resumed_from_display: str | None
    resumed_as_display: str | None

    @classmethod
    async def of(
        cls,
        resumed_from: ResumedFromInfo | None,
        resumed_as: str | None,
        detail_by_id: DetailById,
    ) -> ResumeLineage:
        latest = await _leaf(resumed_as, detail_by_id)
        return cls(
            resumed_from=resumed_from,
            resumed_as=resumed_as,
            latest_resumed_as=latest,
            resumed_from_display=(
                None
                if resumed_from is None
                else f"Resumed from {resumed_from.parent_execution_id} "
                f"at phase {resumed_from.resume_phase_id}"
            ),
            resumed_as_display=_resumed_as_display(resumed_as, latest),
        )


async def _leaf(child: str | None, detail_by_id: DetailById) -> str | None:
    """``child`` followed along `resumed_as` to the last run in the chain.

    A child whose row is not there yet (its start is still being applied)
    is itself the latest run anyone can open. The seen-set is not a business
    rule: resume admits a parent once, so a cycle is a corrupt read model,
    and stopping is better than hanging a page on it.
    """
    seen: set[str] = set()
    while child is not None and child not in seen:
        seen.add(child)
        row = await detail_by_id(child)
        if row is None or row.resumed_as is None:
            return child
        child = row.resumed_as
    return child


def _resumed_as_display(resumed_as: str | None, latest: str | None) -> str | None:
    if resumed_as is None:
        return None
    if latest is None or latest == resumed_as:
        return f"Resumed as {resumed_as}"
    return f"Resumed as {resumed_as}; latest continuation {latest}"
