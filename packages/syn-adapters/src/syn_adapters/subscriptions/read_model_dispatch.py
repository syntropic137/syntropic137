"""One way to deliver an event to a read model, in every mode (#2265).

Production delivers through the ``SubscriptionCoordinator`` (ADR-055), which
calls ``CheckpointedProjection.handle_event`` on each registered projection.
Plain-class projections reach it wrapped in an adapter, and each adapter
decides the handler name and the payload shape (``model_dump()``, a typed
payload, a stripped namespace).

Test and offline runs have no coordinator, but their writes must read back
exactly as they would in production. They used to get there through a
hand-kept event map that disagreed with the coordinator on both event names
and payloads. Now they go through the same ``handle_event`` on the same
adapters, chosen by :func:`as_checkpointed`, which the coordinator's own
registration uses too. A handler is therefore reached in test mode if and
only if it is reached in production.
"""

from __future__ import annotations

import logging
from functools import cache
from typing import TYPE_CHECKING

from event_sourcing import (
    CheckpointedProjection,
    DispatchContext,
    ProjectionCheckpoint,
    ProjectionResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from event_sourcing import DomainEvent, EventEnvelope

logger = logging.getLogger(__name__)


class _NoCheckpoints:
    """Checkpoints for a caller with no durable position: none are kept.

    The in-process caller hands over each event exactly once and never resumes,
    so a saved position would only be a value nothing reads. Holding none also
    means nothing is skipped as "already processed".
    """

    async def get_checkpoint(self, projection_name: str) -> ProjectionCheckpoint | None:  # noqa: ARG002
        return None

    async def save_checkpoint(self, checkpoint: ProjectionCheckpoint) -> None:
        pass

    async def delete_checkpoint(self, projection_name: str) -> None:
        pass

    async def get_all_checkpoints(self) -> list[ProjectionCheckpoint]:
        return []


@cache
def _adapters() -> tuple[tuple[type, Callable[..., CheckpointedProjection]], ...]:
    """Each plain-class projection the coordinator registers, with its adapter.

    Imported on first use: the domain projections import this package.
    """
    from syn_adapters.projections.realtime import RealTimeProjection
    from syn_adapters.subscriptions.projection_adapters import (
        ExecutionCostAdapter,
        SessionCostAdapter,
        ToolTimelineAdapter,
    )
    from syn_adapters.subscriptions.realtime_adapter import (
        OrganizationListAdapter,
        RealTimeProjectionAdapter,
        RepoCorrelationAdapter,
        RepoListAdapter,
        SystemListAdapter,
        TriggerHistoryAdapter,
    )
    from syn_domain.contexts.agent_sessions.slices.session_cost.projection import (
        SessionCostProjection,
    )
    from syn_domain.contexts.agent_sessions.slices.tool_timeline import ToolTimelineProjection
    from syn_domain.contexts.github.slices.trigger_history.projection import (
        TriggerHistoryProjection,
    )
    from syn_domain.contexts.orchestration.slices.execution_cost.projection import (
        ExecutionCostProjection,
    )
    from syn_domain.contexts.organization._shared.organization_projection import (
        OrganizationProjection,
    )
    from syn_domain.contexts.organization.slices.list_repos.projection import RepoProjection
    from syn_domain.contexts.organization.slices.list_systems.projection import SystemProjection
    from syn_domain.contexts.organization.slices.repo_correlation import (
        RepoCorrelationProjection,
    )

    return (
        (OrganizationProjection, OrganizationListAdapter),
        (SystemProjection, SystemListAdapter),
        (RepoProjection, RepoListAdapter),
        (RepoCorrelationProjection, RepoCorrelationAdapter),
        (TriggerHistoryProjection, TriggerHistoryAdapter),
        (ToolTimelineProjection, ToolTimelineAdapter),
        (ExecutionCostProjection, ExecutionCostAdapter),
        (SessionCostProjection, SessionCostAdapter),
        (RealTimeProjection, RealTimeProjectionAdapter),
    )


def as_checkpointed(projection: object) -> CheckpointedProjection | None:
    """The form in which the coordinator delivers events to ``projection``.

    A ``CheckpointedProjection`` is delivered to directly. A plain-class
    projection the coordinator registers is wrapped in the adapter it is
    registered with. Anything else is not fed by events (``None``), such as
    the session timeline, which the write path records into.
    """
    for projection_type, adapter in _adapters():
        if isinstance(projection, projection_type):
            return adapter(projection)
    if isinstance(projection, CheckpointedProjection):
        return projection
    return None


async def deliver(
    projections: Iterable[CheckpointedProjection],
    envelope: EventEnvelope[DomainEvent],
) -> None:
    """Deliver one live event to every projection subscribed to its type.

    The coordinator's call, without its checkpoint skipping or hold-and-retry:
    the in-process caller has no durable position to resume from. A handler
    that fails is logged and the others still run, as a failure here must not
    hide the event from the read models that did handle it.
    """
    event_type = envelope.metadata.event_type or "Unknown"
    global_nonce = envelope.metadata.global_nonce or 0
    context = DispatchContext(
        is_catching_up=False, global_nonce=global_nonce, live_boundary_nonce=global_nonce
    )
    for projection in projections:
        if not projection.should_handle_event_type(event_type):
            continue
        result = await projection.handle_event(envelope, _NoCheckpoints(), context)
        if result == ProjectionResult.FAILURE:
            logger.error(
                "Projection returned FAILURE",
                extra={"projection_name": projection.get_name(), "event_type": event_type},
            )
