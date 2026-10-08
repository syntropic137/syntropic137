"""Keep the provisioning event's workspace-to-execution link after teardown.

Docker labels disappear with their container. This index deliberately keeps
every provisioning, not just the current phase, so old directories can still
be attributed after completion or restart. It is rebuilt from Lane 1 events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.orchestration.domain.events.WorkspaceProvisionedForPhaseEvent import (
    WorkspaceProvisionedForPhaseEvent,
)
from syn_domain.contexts.orchestration.slices.workspace_ownership.value_objects import (
    WorkspaceOwner,
)

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore


class WorkspaceOwnershipProjection(AutoDispatchProjection):
    """A store-backed index, shared by the coordinator and janitor's reader."""

    PROJECTION_NAME = "workspace_ownership"
    VERSION = 1

    def __init__(self, store: ProjectionStore) -> None:
        self._store = store

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    async def clear_all_data(self) -> None:
        await self._store.delete_all(self.PROJECTION_NAME)

    async def on_workspace_provisioned_for_phase(
        self, event_data: WorkspaceProvisionedForPhaseEvent
    ) -> None:
        event = WorkspaceProvisionedForPhaseEvent.model_validate(event_data)
        if not event.workspace_id or not event.execution_id:
            raise ValueError("Workspace provisioning must name its workspace and execution")
        owners = await self.owners(event.workspace_id)
        record = WorkspaceOwner(
            workspace_id=event.workspace_id,
            execution_ids=tuple(sorted(owners | {event.execution_id})),
        )
        await self._store.save(
            self.PROJECTION_NAME, event.workspace_id, record.model_dump(mode="json")
        )

    async def owners(self, workspace_id: str) -> set[str]:
        stored = await self._store.get(self.PROJECTION_NAME, workspace_id)
        return set() if stored is None else set(WorkspaceOwner.model_validate(stored).execution_ids)
