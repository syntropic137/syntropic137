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
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    RecordPhasePushCommand,
)
from syn_shared.events import GIT_PUSH

if TYPE_CHECKING:
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


class _Push(BaseModel):
    """The fields of the hook's `context.git` this reads; the rest are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    remote: str = _ORIGIN
    branch: str = ""
    sha: str = ""
    repo: str = ""


class _PushContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    git: _Push


class _HookLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    event_type: str
    context: _PushContext | None = None


async def observe_push(embedded: object, on_push: PushObserver | None) -> None:
    """Tell ``on_push`` of the push ``embedded`` reports, if it is one to origin.

    ``embedded`` is a hook event as parsed from the agent's tool output.
    """
    if on_push is None:
        return
    try:
        event = _HookLine.model_validate(embedded)
    except ValidationError:
        return
    if event.event_type != GIT_PUSH or event.context is None:
        return
    push = event.context.git
    if push.remote != _ORIGIN or not (push.repo and push.branch and push.sha):
        return
    if push.branch == "HEAD":
        return
    await on_push(push.repo, push.branch, push.sha)
