"""A push the running phase's own workspace made, recorded as it is made (PC-128).

The workspace's pre-push hook reports each push into the agent's tool output
as a `git_push` event, which `EmbeddedEventScanner` already finds for Lane 2.
This module is the one crossing from that report into Lane 1: it records a
push on the execution as `PhaseCommitPushed`, while the phase is still alive -
the run a deploy orphans never reaches anything later.

The hook alone is not evidence of a push. It runs BEFORE git pushes, and it
reports the checked-out branch and HEAD, not the ref being pushed: a rejected
push, or `git push origin other:other` from a branch someone else moved,
reports that branch at a commit this run never pushed. So a push is recorded
only when git's own status line - printed after the remote accepted the
update - names the hook's branch as the destination and updates it to the
hook's SHA. A rejected, up-to-date, quiet or other-ref push has no such line
and records nothing.

That status line must belong to the same push as the hook. One tool result
can hold several pushes, and git's accepted line for one confirms nothing
about another's hook. A push's hook writes its line to stderr before git
writes `To <url>` and the status table there, so a hook's push is the output
after its line and before the next push's hook: it is confirmed only when
that span holds exactly one `To` block, for the hook's repository. Anything
else is ambiguous and establishes nothing.

Recording is best effort and never raises into the stream: a push the run
fails to record leaves a resume exactly where it was before PC-128, refusing
a moved branch, which is the safe direction.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from syn_domain.contexts.orchestration.domain.aggregate_execution.commands import (
    RecordPhasePushCommand,
)
from syn_shared.events import GIT_PUSH

if TYPE_CHECKING:
    from collections.abc import Sequence

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


#: git's per-ref status line for an accepted update (git-push(1), OUTPUT):
#: ` <old>..<new> <from> -> <to>`, `+ <old>...<new> <from> -> <to>` or
#: `* [new branch] <from> -> <to>`. Rejections (`!`), deletions (`-`) and
#: `[up to date]` (`=`) are deliberately not matched.
_ACCEPTED_UPDATE = re.compile(
    r"^(?:[+*]\s+)?"
    r"(?:[0-9a-f]{4,40}\.\.\.?(?P<new>[0-9a-f]{4,40})|(?P<created>\[new branch\]))"
    r"\s+(?P<source>\S+)\s+->\s+(?P<destination>\S+)(?:\s+\(.*\))?$"
)
_HEADS = "refs/heads/"
#: git opens each push's status table with this, then the remote URL.
_TO = "To "


def _branch_name(ref: str) -> str:
    return ref.removeprefix(_HEADS)


def _repository_of(url: str) -> str:
    """A remote URL's repository name, derived as the pre-push hook derives ``repo``."""
    return url.rstrip("/").rsplit("/", 1)[-1].replace(".git", "")


def _is_status(line: str) -> bool:
    """Whether ``line`` is a row of git's per-ref status table: ` <flag> ... <from> -> <to>`."""
    return line.startswith(" ") and " -> " in line


def _status_table(push_output: Sequence[str], repository: str) -> list[str]:
    """The status rows of the one push ``push_output`` reports to ``repository``.

    Empty unless exactly one `To <url>` names it: two mean two pushes, and a
    status row there cannot be told apart from the hook's own.
    """
    to = [i for i, line in enumerate(push_output) if line.startswith(_TO)]
    if len(to) != 1 or _repository_of(push_output[to[0]][len(_TO) :].strip()) != repository:
        return []
    rows: list[str] = []
    for line in push_output[to[0] + 1 :]:
        if not _is_status(line):
            break
        rows.append(line.strip())
    return rows


def git_accepted(push_output: Sequence[str], push: _Push) -> bool:
    """Whether git's report of this one push shows origin's branch updated to its SHA.

    ``push_output`` is the output of the push ``push`` is the hook event of
    (see `push_operation`). An update line names the new commit abbreviated,
    which must be a prefix of the SHA. A created branch names none, so its
    source must be the branch the hook read the SHA from - the checked-out
    branch, or HEAD itself.
    """
    for row in _status_table(push_output, push.repo):
        update = _ACCEPTED_UPDATE.match(row)
        if update is None or _branch_name(update["destination"]) != push.branch:
            continue
        if update["new"] is not None and push.sha.startswith(update["new"]):
            return True
        if update["created"] is not None and _branch_name(update["source"]) in (
            push.branch,
            "HEAD",
        ):
            return True
    return False


def _is_push_hook(line: str) -> bool:
    try:
        return _HookLine.model_validate_json(line.strip()).event_type == GIT_PUSH
    except ValidationError:
        return False


def push_operation(lines: Sequence[str], hook_index: int) -> list[str]:
    """The output of the push whose hook printed ``lines[hook_index]``.

    Everything after the hook's line, up to the next push's hook line.
    """
    after = lines[hook_index + 1 :]
    end = next((i for i, line in enumerate(after) if _is_push_hook(line)), len(after))
    return list(after[:end])


def _hook_push(embedded: object) -> _Push | None:
    """The push to origin's named branch ``embedded`` reports, or None."""
    try:
        event = _HookLine.model_validate(embedded)
    except ValidationError:
        return None
    if event.event_type != GIT_PUSH or event.context is None:
        return None
    push = event.context.git
    if push.remote != _ORIGIN or not (push.repo and push.branch and push.sha):
        return None
    return None if push.branch == "HEAD" else push


async def observe_push(
    embedded: object, push_output: Sequence[str], on_push: PushObserver | None
) -> None:
    """Tell ``on_push`` of the push ``embedded`` reports, if git confirms it to origin.

    ``embedded`` is a hook event as parsed from the agent's tool output, and
    ``push_output`` is that push's own output (`push_operation`), where git
    reports what it pushed.
    """
    if on_push is None:
        return
    push = _hook_push(embedded)
    if push is None or not git_accepted(push_output, push):
        return
    await on_push(push.repo, push.branch, push.sha)
