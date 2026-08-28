# See ADR-066: this application service runs in syn-api but does no I/O
# beyond projection reads, mirroring ``claude_plugin_resolution_service.py``
# (issue #726). Skills have no global scope in this plan (issue #772), so
# this service is deliberately thinner than the plugin one: there is no
# ``ensure_registered`` step, no global registry projection, and no
# innermost-wins-by-name layering. Merge semantics are simpler: phase scope
# wins only on an exact identity collision; otherwise workflow and phase
# scopes are additive.
"""Skill resolution service (issue #772).

Single responsibility: ``resolve_for_phase(...)`` merges a phase's
workflow-scope and phase-scope ``SkillRef``s and resolves each one against
the lock projection into a ``ResolvedSkill``. Used by
``ExecuteWorkflowHandler`` (via the injected ``phase_skill_resolver``
callable) to populate ``ExecutablePhase.skills``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration import SkillNotRegistered

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syn_domain.contexts.orchestration._shared.resolved_skill import ResolvedSkill
    from syn_domain.contexts.orchestration._shared.skill_ref import SkillRef
    from syn_domain.contexts.orchestration.slices.register_skill.projection import (
        SkillLockProjection,
    )

logger = logging.getLogger(__name__)


def _merge_skill_refs(
    workflow_refs: Sequence[SkillRef],
    phase_refs: Sequence[SkillRef],
) -> list[SkillRef]:
    """Union workflow- and phase-scope refs, deduped by identity triple.

    Identity is ``(source_url, version, skill_name)`` (``SkillRef.__eq__``).
    Workflow scope is additive: every workflow-scope ref is included unless
    a phase-scope ref shares the exact same identity, in which case the
    phase-scope ref wins (they are equal by identity but the phase entry is
    kept, matching "phase scope wins on collision"). Declaration order is
    preserved: workflow refs first, then any phase refs not already present.
    """
    ordered: dict[tuple[str, str, str], SkillRef] = {}
    for ref in workflow_refs:
        ordered[(ref.source_url, ref.version, ref.skill_name)] = ref
    for ref in phase_refs:
        ordered[(ref.source_url, ref.version, ref.skill_name)] = ref
    return list(ordered.values())


class SkillResolutionService:
    """Resolves a phase's skill refs against the lock projection (issue #772)."""

    def __init__(self, lock_projection: SkillLockProjection) -> None:
        self._lock = lock_projection

    async def resolve_for_phase(
        self,
        workflow_skills: Sequence[SkillRef],
        phase_skills: Sequence[SkillRef],
    ) -> tuple[ResolvedSkill, ...]:
        """Return the materializer-ready set of resolved skills for a phase.

        Merges workflow- and phase-scope refs (phase wins on exact identity
        collision, workflow scope additive), then looks each one up in the
        lock projection. Raises ``SkillNotRegistered`` for the first miss --
        the CLI is responsible for calling
        ``POST /skills/registrations`` before installing/executing a
        workflow that declares skills.
        """
        merged = _merge_skill_refs(workflow_skills, phase_skills)
        resolved = [await self._lookup(ref) for ref in merged]
        return tuple(resolved)

    async def _lookup(self, ref: SkillRef) -> ResolvedSkill:
        from syn_domain.contexts.orchestration._shared.resolved_skill import ResolvedSkill

        entry = await self._lock.get(ref.source_url, ref.version, ref.skill_name)
        if entry is None:
            logger.info(
                "Skill referenced by workflow is not in the lock",
                extra={
                    "skill_name": ref.skill_name,
                    "source_url": ref.source_url,
                    "version": ref.version,
                },
            )
            raise SkillNotRegistered(ref.source_url, ref.version, ref.skill_name)
        return ResolvedSkill(
            skill_name=entry.skill_name,
            source_url=entry.source_url,
            version=entry.version,
            resolved_sha=entry.resolved_sha,
            tree_storage_prefix=entry.tree_storage_prefix,
        )
