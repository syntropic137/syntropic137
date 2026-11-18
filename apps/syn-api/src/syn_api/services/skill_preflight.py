"""Every skill a workflow declares resolves, checked before any start exists (#998, #1003).

The one check both entrances share. `POST /execute` answers a refusal with a
422 (#998); the trigger dispatcher records it as the reason its trigger
`failed` (#1003). Both used to discover the same refusal later, inside a
background task and before the execution was first persisted, where there is
no execution row to mark and the resolver's message - which names the skill,
its source, its pinned version and how to fix it - reached only a log file.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from syn_domain.contexts._shared.start_refusal import WorkflowNotStartableError
from syn_domain.contexts.orchestration import SkillError

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration import SkillRef, WorkflowTemplateAggregate

logger = logging.getLogger(__name__)

#: A preflight that hangs is worse than one that fails: it converts a fast 200
#: into a request that never returns. The resolver reads Postgres and the
#: projection store supplies no timeout of its own.
SKILL_PREFLIGHT_TIMEOUT_SECONDS = 10.0


class UnresolvableSkillRefError(WorkflowNotStartableError):
    """A declared skill does not resolve; ``str(exc)`` names the phase, the skill and the fix."""


class SkillPreflightUnavailableError(Exception):
    """The resolver could not answer. Says nothing about the workflow; retry shortly.

    Its text is constant on purpose: the cause can be a database error carrying
    a DSN, so it is chained and logged, never reflected.
    """

    def __init__(self) -> None:
        super().__init__("skill validation is temporarily unavailable; retry shortly")


def _unique_skill_refs(
    workflow: WorkflowTemplateAggregate,
) -> list[tuple[SkillRef, str]]:
    """Each distinct skill ref once, paired with the phase that declared it.

    Split from the preflight because collecting refs and talking to the resolver
    are different jobs, and together they pushed one function past the
    complexity thresholds. The pairing is what lets an error name the phase that
    actually failed rather than guessing afterwards.

    Deduplicates on `(source_url, version, skill_name)` because resolution
    merges by exactly that identity - the answer cannot vary by phase, so an
    N-phase workflow sharing one ref should cost one lookup, not N.
    """
    seen: dict[tuple[str, str, str], tuple[SkillRef, str]] = {}
    for ref in workflow.skills or ():
        seen.setdefault((ref.source_url, ref.version, ref.skill_name), (ref, "<workflow>"))
    for phase in workflow.phases:
        for ref in phase.skills or ():
            seen.setdefault((ref.source_url, ref.version, ref.skill_name), (ref, phase.phase_id))
    return list(seen.values())


async def require_resolvable_skills(workflow: WorkflowTemplateAggregate) -> None:
    """Resolve every declared skill NOW, or raise.

    Raises :class:`UnresolvableSkillRefError` when a ref does not resolve, and
    :class:`SkillPreflightUnavailableError` when the resolver cannot answer.

    FAILS CLOSED on infrastructure. An earlier version skipped the preflight
    when the resolver could not be constructed, so as not to block all work on a
    degraded subsystem. That was wrong here: the background handler constructs
    the SAME resolver moments later, before persistence, so skipping merely
    relocated the failure back into the window this exists to close.

    The timeout encloses the FACTORY as well as resolution. Constructing the
    service is cheap today, but it is the call that would acquire a pool or do a
    DNS lookup tomorrow, and a timeout that starts after it would not bound the
    caller at all.
    """
    refs = _unique_skill_refs(workflow)
    if not refs:
        return

    try:
        async with asyncio.timeout(SKILL_PREFLIGHT_TIMEOUT_SECONDS):
            from syn_api._wiring import get_skill_resolution_service

            service = await get_skill_resolution_service()
            for ref, owner in refs:
                try:
                    await service.resolve_for_phase((), (ref,))
                except SkillError as exc:
                    # Caught PER REF so the message names the phase that
                    # actually declared it. Catching outside the loop meant
                    # guessing afterwards, and the guess - first phase with any
                    # skill - is wrong whenever a later phase is the broken one.
                    raise UnresolvableSkillRefError(f"phase '{owner}': {exc}") from exc
    except UnresolvableSkillRefError:
        raise
    except Exception as exc:
        logger.warning("Skill preflight could not complete", exc_info=True)
        raise SkillPreflightUnavailableError from exc


async def require_resolvable_skills_for(workflow_id: str) -> None:
    """:func:`require_resolvable_skills` for a stored workflow, by id.

    For the trigger dispatcher, which holds an id rather than the aggregate. A
    missing workflow is not this check's business: `handle()` raises
    `WorkflowNotFoundError` for it, as `validate_stored_declarations` also
    leaves it.
    """
    from syn_adapters.storage import get_workflow_repository

    workflow = await get_workflow_repository().get_by_id(workflow_id)
    if workflow is not None:
        await require_resolvable_skills(workflow)
