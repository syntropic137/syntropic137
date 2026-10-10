"""Records what a phase shipped into the ledger, as its stream is read.

Built once per phase run with the execution's attribution and handed to the
phase's ``ObservabilityCollector``, which calls it:

- ``commit_seen`` for each ``git_commit`` hook event (sha, repo, time);
- ``command_started`` with the FULL command of each shell tool call;
- ``command_finished`` with that call's success and FULL output.

A PR is recorded only when ``gh_pr_create.created_pull_request`` accepts the
command and its output. Never raises: recording what was shipped must not
fail the phase that shipped it, so a ledger error is logged and dropped (the
backfill can restore it).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration._shared.gh_pr_create import (
    created_pull_request,
    is_gh_pr_create,
)
from syn_domain.contexts.orchestration._shared.shipped_ledger import (
    CommitShipped,
    ExecutionAttribution,
    PullRequestOpened,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from syn_domain.contexts.orchestration._shared.shipped_ledger import ShippedLedger
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ShippedRecorder:
    """One phase's link from its stream to the shipped ledger."""

    ledger: ShippedLedger
    attribution: ExecutionAttribution
    clock: Callable[[], datetime] = _now
    _pr_commands: dict[str, str] = field(default_factory=dict)
    """tool_use_id -> command, for calls that ran ``gh pr create``."""

    async def commit_seen(self, sha: str | None, repo: str | None) -> None:
        """A ``git_commit`` hook event from this phase."""
        repository = self.attribution.repository_for(repo)
        if not sha or repository is None:
            logger.debug("Commit not attributable (sha=%s repo=%s)", sha, repo)
            return
        a = self.attribution
        await self._safely(
            self.ledger.record_commit(
                CommitShipped(
                    sha=sha,
                    execution_id=a.execution_id,
                    workflow_id=a.workflow_id,
                    workflow_name=a.workflow_name,
                    repository=repository,
                    committed_at=self.clock(),
                )
            )
        )

    def command_started(self, tool_use_id: str, command: object) -> None:
        """A shell tool call began; remembered only if it runs ``gh pr create``."""
        if isinstance(command, str) and is_gh_pr_create(command):
            self._pr_commands[tool_use_id] = command

    async def command_finished(self, tool_use_id: str, success: bool, output: str) -> None:
        """That call ended: record the PR it created, if it created one."""
        command = self._pr_commands.pop(tool_use_id, None)
        if command is None:
            return
        created = created_pull_request(command, success, output)
        if created is None:
            return
        a = self.attribution
        await self._safely(
            self.ledger.record_pull_request_opened(
                PullRequestOpened(
                    repository=created.repository,
                    number=created.number,
                    url=created.url,
                    execution_id=a.execution_id,
                    workflow_id=a.workflow_id,
                    workflow_name=a.workflow_name,
                    created_at=self.clock(),
                )
            )
        )

    @staticmethod
    async def _safely(write: Awaitable[None]) -> None:
        try:
            await write
        except Exception:
            logger.warning(
                "Shipped ledger write failed; the backfill can restore it", exc_info=True
            )


def shipped_recorder(
    ledger: ShippedLedger | None, aggregate: WorkflowExecutionAggregate, execution_id: str
) -> ShippedRecorder | None:
    """The recorder for a phase of ``aggregate``'s run, or None with no ledger wired."""
    if ledger is None:
        return None
    attribution = ExecutionAttribution(
        execution_id=execution_id,
        workflow_id=aggregate.workflow_id or "",
        workflow_name=aggregate.workflow_name or "",
        repositories=tuple(c.repository for c in aggregate.start_pins.source_commits),
    )
    return ShippedRecorder(ledger=ledger, attribution=attribution)
