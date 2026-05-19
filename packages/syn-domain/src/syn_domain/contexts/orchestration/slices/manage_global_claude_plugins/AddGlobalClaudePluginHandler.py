# See ADR-066: this slice handler runs in syn-api and reaches only the lock
# projection plus the global-registry repo, per the thin-API rule. The previous
# auto-register fallback (which transitively triggered git work) is gone in
# Phase A; callers must register the plugin first via
# ``POST /claude-plugins/registrations``.
"""AddGlobalClaudePlugin command handler (issue #726, Phase A redesign).

Looks up an already-registered plugin by ``(name, version)`` in the lock
projection and adds it to the singleton ``GlobalClaudePluginRegistryAggregate``.
Idempotent on duplicate-name (returns the existing entry instead of raising).

If the plugin is not in the lock projection the handler raises
``ClaudePluginNotRegistered`` so the route can return a clear 404 with
``error_code=claude_plugin_not_registered``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from event_sourcing import StreamAlreadyExistsError

from syn_domain.contexts.orchestration._shared.claude_plugin_errors import (
    ClaudePluginNotRegistered,
)
from syn_domain.contexts.orchestration.domain.aggregate_global_claude_plugin_registry.GlobalClaudePluginRegistryAggregate import (
    GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID,
    GlobalClaudePluginRegistryAggregate,
)
from syn_domain.contexts.orchestration.domain.commands.AddGlobalClaudePluginCommand import (
    AddGlobalClaudePluginCommand,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.ports.GlobalClaudePluginRegistryRepositoryPort import (
        GlobalClaudePluginRegistryRepositoryPort,
    )
    from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
        ClaudePluginLockProjection,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AddGlobalClaudePluginResult:
    """What the global add path returns to the caller."""

    name: str
    source_url: str
    version: str
    resolved_sha: str


class AddGlobalClaudePluginHandler:
    def __init__(
        self,
        repo: GlobalClaudePluginRegistryRepositoryPort,
        lock_projection: ClaudePluginLockProjection,
    ) -> None:
        self._repo = repo
        self._lock = lock_projection

    async def handle(self, name: str, version: str) -> AddGlobalClaudePluginResult:
        # Lock-first: refuse to add anything that has not been registered.
        # The CLI must POST /claude-plugins/registrations before calling this.
        entry = await self._lock.get_by_name_version(name, version)
        if entry is None:
            raise ClaudePluginNotRegistered(name, version)

        command = AddGlobalClaudePluginCommand(
            aggregate_id=GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID,
            name=entry.name,
            source_url=entry.source_url,
            version=entry.version,
            resolved_sha=entry.resolved_sha,
        )
        result = AddGlobalClaudePluginResult(
            name=entry.name,
            source_url=entry.source_url,
            version=entry.version,
            resolved_sha=entry.resolved_sha,
        )

        # WHY (issue #726): two callers can pass the ``aggregate is None`` check
        # before either commits, so both would attempt ``save_new``. The losing
        # writer hits ``StreamAlreadyExistsError``; we recover by reloading and
        # applying the command on the now-existing aggregate. The aggregate's
        # domain rule (raises ``ValueError`` on duplicate name) handles
        # idempotency cleanly.
        for attempt in range(2):
            if await self._try_add_once(command, entry.name, attempt):
                return result

        # WHY: two save_new races back-to-back is impossible because the second
        # iteration always sees the persisted aggregate and takes the save()
        # path. This branch only runs if the event store is misbehaving.
        msg = "Failed to add global claude plugin after retry; event store inconsistent"
        raise RuntimeError(msg)

    async def _try_add_once(
        self,
        command: AddGlobalClaudePluginCommand,
        plugin_name: str,
        attempt: int,
    ) -> bool:
        """One pass of the add loop. Returns True when work is done (success
        or idempotent no-op), False when the caller must retry.
        """
        aggregate = await self._repo.get_by_id(GLOBAL_CLAUDE_PLUGIN_REGISTRY_STREAM_ID)
        if aggregate is None:
            return await self._create_new_registry(command, plugin_name, attempt)
        return await self._extend_existing_registry(aggregate, command, plugin_name)

    async def _create_new_registry(
        self,
        command: AddGlobalClaudePluginCommand,
        plugin_name: str,
        attempt: int,
    ) -> bool:
        """First-write path: no aggregate yet. Returns True on success/no-op,
        False if a concurrent writer beat us (caller should retry).
        """
        fresh = GlobalClaudePluginRegistryAggregate()
        if self._apply_or_short_circuit(fresh, command, plugin_name) is None:
            return True
        try:
            await self._repo.save_new(fresh)
        except StreamAlreadyExistsError:
            logger.info(
                "Concurrent global registry create; reloading and retrying",
                extra={"plugin_name": plugin_name, "attempt": attempt},
            )
            return False
        return True

    async def _extend_existing_registry(
        self,
        aggregate: GlobalClaudePluginRegistryAggregate,
        command: AddGlobalClaudePluginCommand,
        plugin_name: str,
    ) -> bool:
        if self._apply_or_short_circuit(aggregate, command, plugin_name) is None:
            return True
        await self._repo.save(aggregate)
        return True

    def _apply_or_short_circuit(
        self,
        aggregate: GlobalClaudePluginRegistryAggregate,
        command: AddGlobalClaudePluginCommand,
        plugin_name: str,
    ) -> GlobalClaudePluginRegistryAggregate | None:
        """Apply ``add`` to the aggregate or return None on duplicate-by-name.

        WHY: the aggregate raises ``ValueError`` on a duplicate name, which we
        treat as idempotent success. Returning ``None`` lets the caller skip
        the save call entirely.
        """
        try:
            aggregate.add(command)
        except ValueError as exc:
            logger.info(
                "Global claude plugin already present, returning existing entry",
                extra={"plugin_name": plugin_name, "detail": str(exc)},
            )
            return None
        return aggregate
