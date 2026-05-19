# See ADR-066: this application service runs in syn-api but does no I/O beyond
# projection reads. After the #726 Phase A redesign, ``ensure_registered`` is
# pure validation: any missing plugin must be registered by the CLI first via
# POST /claude-plugins/registrations.
"""Claude plugin resolution service (issue #726, Phase A redesign).

Two responsibilities:

1. ``ensure_registered(workflow_def)`` -- validate that every
   ``claude_plugins:`` ref a workflow declares (workflow scope, every phase,
   plus the global set) is already in the lock projection. Raises
   ``ClaudePluginNotRegistered`` listing the first missing ref so the API can
   return a 422 with a stable error code. The API does NOT fetch on demand.

2. ``resolve_for_phase(...)`` -- innermost-wins per-phase resolution against
   the lock projection. Used by the workflow execution dispatcher. Identical
   semantics to the pre-#726 implementation; only ``ensure_registered`` changed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.claude_plugin_errors import (
    ClaudePluginNotRegistered,
)

# WHY: ClaudePluginRef is constructed at runtime in _collect_unique_refs when
# rehydrating refs from the global registry projection; hoist the import so the
# hot loop does not pay a per-iteration import cost.
from syn_domain.contexts.orchestration._shared.claude_plugin_ref import (
    ClaudePluginRef,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
        ResolvedClaudePlugin,
    )
    from syn_domain.contexts.orchestration._shared.workflow_definition import (
        WorkflowDefinition,
    )
    from syn_domain.contexts.orchestration.slices.manage_global_claude_plugins.projection import (
        GlobalClaudePluginsProjection,
    )
    from syn_domain.contexts.orchestration.slices.register_claude_plugin.projection import (
        ClaudePluginLockProjection,
    )

logger = logging.getLogger(__name__)


def _extend_unique_refs(
    ordered: list[ClaudePluginRef],
    seen: set[tuple[str, str, str]],
    refs: Iterable[ClaudePluginRef],
) -> None:
    """Append refs to ``ordered`` skipping any whose dedup key is in ``seen``.

    WHY a single helper: workflow, phase, and global passes all want the same
    dedup semantics; inlining each made the orchestrator overflow on cognitive
    complexity.
    """
    for ref in refs:
        key = (ref.source_url, ref.version, ref.name)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(ref)


def _log_override(
    scope_name: str,
    prev: tuple[str, ClaudePluginRef],
    ref: ClaudePluginRef,
) -> None:
    logger.info(
        "Claude plugin override at %s scope shadows %s scope",
        scope_name,
        prev[0],
        extra={
            "plugin_name": ref.name,
            "displaced_version": prev[1].version,
            "displaced_scope": prev[0],
            "winning_version": ref.version,
            "winning_scope": scope_name,
        },
    )


def _select_innermost_per_name(
    scope_order: list[tuple[str, list[ClaudePluginRef]]],
) -> dict[str, tuple[str, ClaudePluginRef]]:
    """Innermost-wins layering: phase > workflow > global, keyed by name."""
    chosen: dict[str, tuple[str, ClaudePluginRef]] = {}
    for scope_name, refs in scope_order:
        for ref in refs:
            prev = chosen.get(ref.name)
            if prev is not None and prev[1].version != ref.version:
                _log_override(scope_name, prev, ref)
            chosen[ref.name] = (scope_name, ref)
    return chosen


class ClaudePluginResolutionService:
    """Resolution service: lock-projection-only after Phase A redesign."""

    def __init__(
        self,
        lock_projection: ClaudePluginLockProjection,
        global_projection: GlobalClaudePluginsProjection,
    ) -> None:
        self._lock = lock_projection
        self._global = global_projection

    async def ensure_registered(self, workflow_def: WorkflowDefinition) -> None:
        """Verify every (source_url, version) referenced by the workflow is registered.

        Walks workflow-scope refs, every phase's refs, and the global registry,
        then checks each one against the lock projection. Raises
        ``ClaudePluginNotRegistered`` for the first miss; the workflow must
        not partially install with an unregistered plugin.

        Phase A redesign: this method does NOT fetch. The CLI is responsible
        for calling ``POST /claude-plugins/registrations`` before posting the
        workflow YAML.
        """
        unique_refs = await self._collect_unique_refs(workflow_def)

        for ref in unique_refs:
            existing = await self._lock.get_by_source_version_name(
                ref.source_url, ref.version, ref.name
            )
            if existing is None:
                logger.info(
                    "Claude plugin referenced by workflow is not in the lock",
                    extra={
                        "plugin_name": ref.name,
                        "source_url": ref.source_url,
                        "version": ref.version,
                    },
                )
                raise ClaudePluginNotRegistered(ref.name, ref.version)

    async def _collect_unique_refs(
        self,
        workflow_def: WorkflowDefinition,
    ) -> list[ClaudePluginRef]:
        """Union of workflow-scope, per-phase, and global refs.

        Dedup uses ``(source_url, version, name)``: marketplace repos can host
        many plugins at the same ``(source_url, version)``, so the name must
        be part of the key or we drop legitimately-distinct refs.
        """
        seen: set[tuple[str, str, str]] = set()
        ordered: list[ClaudePluginRef] = []

        _extend_unique_refs(ordered, seen, workflow_def.claude_plugins)
        for phase in workflow_def.phases:
            _extend_unique_refs(ordered, seen, phase.claude_plugins)

        # Global refs come last; they are the outermost scope.
        global_refs = [
            ClaudePluginRef(
                name=entry.name,
                source_url=entry.source_url,
                version=entry.version,
            )
            for entry in await self._global.list_all()
        ]
        _extend_unique_refs(ordered, seen, global_refs)
        return ordered

    async def resolve_for_phase(
        self,
        workflow_claude_plugins: Sequence[ClaudePluginRef],
        phase_claude_plugins: Sequence[ClaudePluginRef],
    ) -> tuple[ResolvedClaudePlugin, ...]:
        """Return the materializer-ready set of resolved plugins for a phase.

        Algorithm:

        1. Walk global -> workflow -> phase, in that order. Innermost wins:
           the LAST entry per ``name`` is kept so phase overrides workflow
           overrides global.
        2. Look up every kept ref in the lock projection. All entries are
           expected to be present because workflow install validated via
           ``ensure_registered`` (and global add validated at add time).
           A miss surfaces as a clear ``LookupError`` -- it indicates the
           install/add invariant was bypassed or the projection is behind.
        3. Return the deduplicated tuple in declaration order so the workspace
           materializer and the ``--plugin-dir`` flag list are deterministic.
        """
        # Step 1: layered union with innermost-wins semantics keyed by name.
        global_entries = await self._global.list_all()
        global_refs: list[ClaudePluginRef] = [
            ClaudePluginRef(name=g.name, source_url=g.source_url, version=g.version)
            for g in global_entries
        ]
        scope_order: list[tuple[str, list[ClaudePluginRef]]] = [
            ("global", global_refs),
            ("workflow", list(workflow_claude_plugins)),
            ("phase", list(phase_claude_plugins)),
        ]
        chosen = _select_innermost_per_name(scope_order)

        # Step 2: lock lookup. Order is preserved by dict insertion order.
        resolved = [await self._lookup_in_lock(name, ref) for name, (_scope, ref) in chosen.items()]
        return tuple(resolved)

    async def _lookup_in_lock(
        self,
        name: str,
        ref: ClaudePluginRef,
    ) -> ResolvedClaudePlugin:
        from syn_domain.contexts.orchestration._shared.resolved_claude_plugin import (
            ResolvedClaudePlugin,
        )

        entry = await self._lock.get_by_source_version_name(ref.source_url, ref.version, name)
        if entry is None:
            msg = (
                f"Claude plugin {ref.source_url}@{ref.version} (name={name}) is "
                "not in the lock projection. ``ensure_registered`` must run "
                "during workflow install or global add before execute time."
            )
            raise LookupError(msg)
        return ResolvedClaudePlugin(
            name=name,
            source_url=entry.source_url,
            version=entry.version,
            resolved_sha=entry.resolved_sha,
            tree_storage_prefix=entry.tree_storage_prefix,
        )
