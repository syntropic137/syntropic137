"""A push the running phase's own workspace made, recorded as it is made (PC-128).

The workspace's pre-push hook reports each push into the agent's tool output
as a `git_push` event, which `EmbeddedEventScanner` already finds for Lane 2.
This module is the one crossing from that report into Lane 1: it reads the
pushed branch and SHA out of the hook's payload and records them on the
execution as `PhaseCommitPushed`, while the phase is still alive - the run a
deploy orphans never reaches anything later.

Recording is best effort and never raises into the stream: a push the run
fails to record leaves a resume exactly where it was before PC-128, refusing
a moved branch, which is the safe direction.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    RecordPhasePushCommand,
)
from syn_shared.events import GIT_PUSH

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.execution_journal import (
        ExecutionJournal,
    )

logger = logging.getLogger(__name__)

_ORIGIN = "origin"


class PushObserver(Protocol):
    """Told of each push the phase's workspace made to origin."""

    async def __call__(self, repository: str, branch: str, sha: str) -> None:
        """``repository`` is the clone's directory name, as the hook reports it."""
        ...


def push_recorder(
    aggregate: WorkflowExecutionAggregate, journal: ExecutionJournal, phase_id: str
) -> PushObserver:
    """Record each push on ``aggregate`` as ``phase_id``'s, and append it at once.

    The processor's own aggregate, not a reloaded copy: it is the instance
    the processor appends to after the agent ends, so a second copy would
    make that append conflict.
    """

    async def record(repository: str, branch: str, sha: str) -> None:
        try:
            aggregate.record_phase_push(
                RecordPhasePushCommand(
                    execution_id=aggregate.id or "",
                    phase_id=phase_id,
                    repository=repository,
                    branch=branch,
                    sha=sha,
                )
            )
            await journal.append(aggregate)
        except Exception:
            logger.exception(
                "Could not record %s's push of %s to %s/%s; a resume will treat a branch "
                "at it as moved",
                phase_id,
                sha,
                repository,
                branch,
            )

    return record


# Any: the hook event is JSON parsed from the agent's tool output (system boundary).
async def observe_push(embedded: Mapping[str, Any], on_push: PushObserver | None) -> None:
    """Tell ``on_push`` of the push ``embedded`` reports, if it is one to origin."""
    if on_push is None or embedded.get("event_type") != GIT_PUSH:
        return
    context = embedded.get("context")
    git = context.get("git") if isinstance(context, dict) else None
    if not isinstance(git, dict):
        return
    repo, branch, sha = git.get("repo"), git.get("branch"), git.get("sha")
    if git.get("remote", _ORIGIN) != _ORIGIN or not (repo and branch and sha) or branch == "HEAD":
        return
    await on_push(str(repo), str(branch), str(sha))
