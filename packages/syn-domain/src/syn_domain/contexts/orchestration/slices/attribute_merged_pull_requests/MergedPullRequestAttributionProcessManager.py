"""Merged-PR attribution ProcessManager (#1728, ADR-025).

Links each pull request to every execution that contributed to it, asks the
forge whether it merged, and records the merge on each contributor's stream as
``PullRequestMergeRecorded``. The scorecard folds those events into merged PRs
and their cost; it never asks GitHub, so a replay rebuilds identical numbers.

PROJECTION SIDE (handle_event): pure. A run is linked to a PR when it reports
  one: the ``pr_number`` and ``repository`` it was started with, a branch its
  resume continued, or a branch a phase observed with a PR open from it as the
  phase completed or failed - which is how a run that OPENED a PR links. A
  resume inherits its parent's links and carries its whole chain into every
  link it makes, so a failed run, its resume and an independent reverify of
  the same PR are all contributors. A branch a phase pushed with no PR open
  from it yet is remembered with the runs that pushed it, because the PR may be
  opened later by a phase that pushes nothing. A replayed ``PullRequestMergeRecorded``
  marks its contributor recorded, so nothing is recorded twice.

PROCESSOR SIDE (process_pending): live only. Asks the forge for the PRs from
  each remembered branch, linking its runs to them, then about each PR not yet
  settled and records the merge for each contributor not yet recorded.
  The platform's clock tick guarantees a pass after a merge on a quiet system.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from event_sourcing import (
    DispatchContext,
    DomainEvent,
    EventEnvelope,
    ProcessManager,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
    ProjectionStore,
)

from syn_domain.contexts.orchestration.domain.aggregate_execution.branch_continuation import (
    repository_slugs_by_name,
)
from syn_domain.contexts.orchestration.domain.events.PhaseCompletedEvent import (
    PhaseCompletedEvent,
)
from syn_domain.contexts.orchestration.domain.events.PullRequestMergeRecordedEvent import (
    PullRequestMergeRecordedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowExecutionStartedEvent import (
    WorkflowExecutionStartedEvent,
)
from syn_domain.contexts.orchestration.domain.events.WorkflowFailedEvent import (
    WorkflowFailedEvent,
)
from syn_domain.contexts.orchestration.slices.attribute_merged_pull_requests.value_objects import (
    BranchContributors,
    PullRequestContributors,
    RunLinks,
    branch_key,
    pull_request_key,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
        BranchObservation,
    )
    from syn_domain.contexts.orchestration.slices.attribute_merged_pull_requests.value_objects import (
        MergeRecorder,
        PullRequestMergePort,
    )

logger = logging.getLogger(__name__)

_STARTED = "WorkflowExecutionStarted"
_FAILED = "WorkflowFailed"
_PHASE_COMPLETED = "PhaseCompleted"
_MERGE_RECORDED = "PullRequestMergeRecorded"
#: Wakes for the processor side: a run ending, and the platform's durable clock,
#: which is what asks again after a PR merges on a quiet system.
_RECHECK_EVENTS = {"WorkflowCompleted", "InventoryReconciliationSweep"}

_RUNS = "merged_pr_attribution_runs"
_PULL_REQUESTS = "merged_pr_attribution_prs"
_BRANCHES = "merged_pr_attribution_branches"
_UNSETTLED = ("open", "merged")
_ORIGIN = "origin"
#: How long a pushed branch is asked about before nobody opening a PR from it
#: is taken as final, so an abandoned branch is not polled forever.
_BRANCH_LOOKUP = timedelta(days=30)


def _reported_pull_requests(event: WorkflowExecutionStartedEvent) -> Iterable[tuple[str, int]]:
    """The PRs a run was started on or continues: its inputs and continued branches."""
    repository = event.inputs.get("repository")
    number = event.inputs.get("pr_number")
    if isinstance(repository, str) and "/" in repository and str(number or "").isdigit():
        yield repository, int(str(number))
    for branch in event.continued_branches or ():
        if branch.pull_request is not None:
            yield branch.repository, branch.pull_request


def _observed_pull_requests(
    run: RunLinks, observations: Iterable[BranchObservation] | None
) -> Iterable[tuple[str, int]]:
    """The PRs open from the branches a phase observed as it completed or failed.

    An observation names the repository by its workspace directory; the run's
    own slugs resolve it, and a name two of them share resolves to neither.
    """
    slugs = repository_slugs_by_name(run.repositories)
    for observed in observations or ():
        repository = observed.repo if "/" in observed.repo else slugs.get(observed.repo)
        if observed.pull_request is not None and repository is not None:
            yield repository, observed.pull_request


def _pushed_branches(
    run: RunLinks, observations: Iterable[BranchObservation] | None
) -> Iterable[tuple[str, str]]:
    """The origin branches a phase pushed with no PR open from them yet."""
    slugs = repository_slugs_by_name(run.repositories)
    for observed in observations or ():
        repository = observed.repo if "/" in observed.repo else slugs.get(observed.repo)
        pushed = observed.remote == _ORIGIN and observed.remote_commit is not None
        if pushed and observed.pull_request is None and repository is not None:
            yield repository, observed.branch


class MergedPullRequestAttributionProcessManager(ProcessManager):
    """Records which executions contributed to each merged PR."""

    PROJECTION_NAME = "merged_pr_attribution"
    VERSION = 3  # 2: folds PhaseCompleted observations; 3: remembers pushed branches (#1728)

    def __init__(
        self,
        store: ProjectionStore | None = None,
        merges: PullRequestMergePort | None = None,
        recorder: MergeRecorder | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._merges = merges
        self._recorder = recorder
        self._clock = clock or (lambda: datetime.now(UTC))

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return {_STARTED, _PHASE_COMPLETED, _FAILED, _MERGE_RECORDED, *_RECHECK_EVENTS}

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,  # noqa: ARG002
    ) -> ProjectionResult:
        """PROJECTION SIDE: link runs to PRs and note recorded merges. No side effects."""
        event_type = envelope.metadata.event_type or "Unknown"
        try:
            event = envelope.event
            if isinstance(event, WorkflowExecutionStartedEvent):
                await self._on_started(event)
            elif isinstance(event, (PhaseCompletedEvent, WorkflowFailedEvent)):
                run = await self._run(event.execution_id)
                observed_at = (
                    event.completed_at
                    if isinstance(event, PhaseCompletedEvent)
                    else event.failed_at
                )
                run = await self._link(run, _observed_pull_requests(run, event.observed_branches))
                await self._remember(
                    run, _pushed_branches(run, event.observed_branches), observed_at
                )
            elif isinstance(event, PullRequestMergeRecordedEvent):
                await self._on_merge_recorded(event)
            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=envelope.metadata.global_nonce or 0,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS
        except Exception:
            logger.exception("Error in merged-PR attribution", extra={"type": event_type})
            return ProjectionResult.FAILURE

    async def _on_started(self, event: WorkflowExecutionStartedEvent) -> None:
        inherited: tuple[str, ...] = ()
        chain: tuple[str, ...] = (event.execution_id,)
        repositories = tuple(c.repository for c in event.source_commits or ())
        parent = RunLinks(execution_id=event.execution_id, chain=())
        if event.resumed_from is not None:
            parent = await self._run(event.resumed_from.parent_execution_id)
            chain = tuple(dict.fromkeys((*parent.chain, event.execution_id)))
            inherited = parent.pull_requests
            repositories = repositories or parent.repositories
        run = RunLinks(execution_id=event.execution_id, chain=chain, repositories=repositories)
        for key in inherited:
            pr = await self._pull_request_by_key(key)
            if pr is not None:
                run = await self._link_one(run, pr.repository, pr.pull_request)
        for key in parent.branches:
            branch = await self._branch_by_key(key)
            if branch is not None:
                run = await self._join_branch(run, branch)
        await self._save_run(run)
        await self._link(run, _reported_pull_requests(event))

    async def _link(self, run: RunLinks, pull_requests: Iterable[tuple[str, int]]) -> RunLinks:
        for repository, number in pull_requests:
            run = await self._link_one(run, repository, number)
        await self._save_run(run)
        return run

    async def _remember(
        self, run: RunLinks, branches: Iterable[tuple[str, str]], observed_at: datetime
    ) -> None:
        for repository, name in branches:
            branch = await self._branch_by_key(branch_key(repository, name))
            run = await self._join_branch(
                run,
                branch
                or BranchContributors(repository=repository, branch=name, observed_at=observed_at),
            )
        await self._save_run(run)

    async def _join_branch(self, run: RunLinks, branch: BranchContributors) -> RunLinks:
        """Add ``run``'s chain to the branch, and to each PR already found from it."""
        joined = branch.with_contributors(run.chain)
        if joined != branch:
            await self._save_branch(joined)
        for number in joined.pull_requests:
            run = await self._link_one(run, joined.repository, number)
        if joined.key in run.branches:
            return run
        return run.model_copy(update={"branches": (*run.branches, joined.key)})

    async def _link_one(self, run: RunLinks, repository: str, number: int) -> RunLinks:
        """Add ``run``'s whole chain to the PR; the run remembers the PR for its resumes."""
        assert self._store is not None
        key = pull_request_key(repository, number)
        pr = await self._pull_request_by_key(key) or PullRequestContributors(
            repository=repository, pull_request=number
        )
        linked = pr.with_contributors(run.chain)
        if linked != pr:
            await self._save_pull_request(linked)
        if key in run.pull_requests:
            return run
        return run.model_copy(update={"pull_requests": (*run.pull_requests, key)})

    async def _on_merge_recorded(self, event: PullRequestMergeRecordedEvent) -> None:
        key = pull_request_key(event.repository, event.pull_request)
        pr = await self._pull_request_by_key(key) or PullRequestContributors(
            repository=event.repository, pull_request=event.pull_request
        )
        pr = pr.with_contributors((event.execution_id,))
        recorded = tuple(dict.fromkeys((*pr.recorded, event.execution_id)))
        await self._save_pull_request(
            pr.model_copy(
                update={"status": "merged", "merged_at": event.merged_at, "recorded": recorded}
            )
        )

    async def process_pending(self) -> int:
        """PROCESSOR SIDE: ask the forge, record each contributor's merge. Live-only."""
        if self._store is None or self._merges is None or self._recorder is None:
            return 0
        for row in await self._store.query(_BRANCHES, filters={"status": "pushed"}):
            await self._find_pull_requests(BranchContributors.model_validate(row))
        recorded = 0
        for status in _UNSETTLED:
            for row in await self._store.query(_PULL_REQUESTS, filters={"status": status}):
                recorded += await self._settle(PullRequestContributors.model_validate(row))
        return recorded

    async def _find_pull_requests(self, branch: BranchContributors) -> None:
        """Link the branch's runs to the PRs from it, once the forge has any."""
        assert self._merges is not None
        if self._clock() - branch.observed_at > _BRANCH_LOOKUP:
            await self._save_branch(branch.model_copy(update={"status": "expired"}))
            return
        numbers = await self._merges.pull_requests_from(branch.repository, branch.branch)
        if not numbers:
            return  # none yet, or unreadable: asked again on the next pass
        for number in numbers:
            key = pull_request_key(branch.repository, number)
            pr = await self._pull_request_by_key(key) or PullRequestContributors(
                repository=branch.repository, pull_request=number
            )
            linked = pr.with_contributors(branch.execution_ids)
            if linked != pr:
                await self._save_pull_request(linked)
        await self._save_branch(
            branch.model_copy(update={"status": "resolved", "pull_requests": numbers})
        )

    async def _settle(self, pr: PullRequestContributors) -> int:
        if pr.status == "merged" and not pr.unrecorded:
            return 0
        merged = pr if pr.merged_at is not None else await self._ask_forge(pr)
        return 0 if merged is None else await self._record_contributors(merged)

    async def _ask_forge(self, pr: PullRequestContributors) -> PullRequestContributors | None:
        """The PR marked merged when the forge says so; None while it is not, or unreadable."""
        assert self._merges is not None
        state = await self._merges.read_merge(pr.repository, pr.pull_request)
        if not state.readable:
            return None  # asked again on the next pass
        if state.merged_at is None:
            if state.closed:
                await self._save_pull_request(pr.model_copy(update={"status": "closed"}))
            return None
        merged = pr.model_copy(update={"status": "merged", "merged_at": state.merged_at})
        await self._save_pull_request(merged)
        return merged

    async def _record_contributors(self, pr: PullRequestContributors) -> int:
        """Record the merge on each contributor not yet recorded; the number recorded."""
        assert self._recorder is not None
        merged_at = pr.merged_at
        assert merged_at is not None
        recorded = 0
        for execution_id in pr.unrecorded:
            try:
                await self._recorder.record_merge(
                    execution_id, pr.repository, pr.pull_request, merged_at
                )
            except Exception:
                logger.exception("Could not record the merge of %s on %s", pr.key, execution_id)
                continue
            pr = pr.model_copy(update={"recorded": (*pr.recorded, execution_id)})
            await self._save_pull_request(pr)
            recorded += 1
        return recorded

    # === Store ===

    async def _branch_by_key(self, key: str) -> BranchContributors | None:
        assert self._store is not None
        row = await self._store.get(_BRANCHES, key)
        return BranchContributors.model_validate(row) if row is not None else None

    async def _save_branch(self, branch: BranchContributors) -> None:
        assert self._store is not None
        await self._store.save(_BRANCHES, branch.key, branch.model_dump(mode="json"))

    async def _run(self, execution_id: str) -> RunLinks:
        assert self._store is not None
        row = await self._store.get(_RUNS, execution_id)
        if row is None:
            return RunLinks(execution_id=execution_id, chain=(execution_id,))
        return RunLinks.model_validate(row)

    async def _save_run(self, run: RunLinks) -> None:
        assert self._store is not None
        await self._store.save(_RUNS, run.execution_id, run.model_dump(mode="json"))

    async def _pull_request_by_key(self, key: str) -> PullRequestContributors | None:
        assert self._store is not None
        row = await self._store.get(_PULL_REQUESTS, key)
        return PullRequestContributors.model_validate(row) if row is not None else None

    async def _save_pull_request(self, pr: PullRequestContributors) -> None:
        assert self._store is not None
        await self._store.save(_PULL_REQUESTS, pr.key, pr.model_dump(mode="json"))

    def get_idempotency_key(self, todo_item: dict[str, str | int | float | bool | None]) -> str:
        """One record per (PR, contributing execution)."""
        return f"{todo_item.get('key', '')}:{todo_item.get('execution_id', '')}"

    async def clear_all_data(self) -> None:
        if self._store is not None:
            await self._store.delete_all(_RUNS)
            await self._store.delete_all(_PULL_REQUESTS)
            await self._store.delete_all(_BRANCHES)
