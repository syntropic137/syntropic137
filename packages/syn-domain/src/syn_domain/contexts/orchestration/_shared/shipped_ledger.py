"""What runs shipped, recorded once at ingestion: the shipped ledger (Lane 2).

Three facts, each with its own identity, and one daily rollup derived from them:

- a **commit** a run made: ``sha``. From the ``git_commit`` hook event the
  run's own stream carries, attributed to the execution and to the repository
  the run cloned under that directory name.
- a **PR a run created**: ``(repository, number)``. From a successful
  ``gh pr create`` the run executed, parsed once from the full command and its
  full output (``gh_pr_create``), never from a display preview.
- a **merge** the GitHub pipeline saw: ``(repository, number)``. Every merge is
  recorded; only merges of PRs a run created are counted.

THE ROLLUP. ``shipped_daily`` holds one row per UTC day x repository x
workflow: ``commits`` and ``prs_opened`` on the day of the fact,
``prs_merged`` on the day of the merge, and ``prs_opened_merged`` on the day
the merged PR was OPENED (the merge-rate cohort numerator). The read path
reads only these rows.

FACTS ARE KEPT, THE ROLLUP IS DERIVED. The three fact tables are the record
and are never reset: merges have no other source, and history keeps only
previews. ``shipped_daily`` is a pure function of the facts, recomputed for
every key a write touches and rebuilt whole when its version changes.

IDEMPOTENT BY IDENTITY, ORDER-INDEPENDENT. Recording a fact twice changes
nothing; when two observations claim one identity, a fixed rule picks the
owner (earliest time, then smaller execution id); a merge recorded before the
PR it merges is counted when the PR arrives, and the other way round; a merge
reported under a repository's new slug is matched through its stable id. So
replaying every input any number of times, in any order, yields the same
rollup. Every ``ShippedLedger`` must hold this, and
``test_shipped_ledger_contract`` checks each against the same cases.

NOT A PROJECTION OVER THE EVENT STORE: its inputs are Lane 2 telemetry, which
the event store never sees, the same shape as ``agent_event_day_rollup``
(#1253).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from syn_domain.contexts._shared.repository_ref import RepositoryRef

if TYPE_CHECKING:
    from collections.abc import Sequence


def repository_key(repository: str) -> str:
    """The identity of a repository: GitHub slugs are case-insensitive."""
    return repository.lower()


def utc_day(instant: datetime) -> date:
    """The UTC calendar day ``instant`` falls on (a naive instant is UTC)."""
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(UTC).date()


@dataclass(frozen=True)
class ExecutionAttribution:
    """Who a phase's work belongs to: its execution, workflow and repositories."""

    execution_id: str
    workflow_id: str
    workflow_name: str
    repositories: tuple[str, ...]
    """``owner/name`` slugs the run cloned."""

    def repository_for(self, reported: str | None) -> str | None:
        """The slug a hook's ``repo`` names: a slug as-is, else a directory name.

        A directory name two cloned repositories share names neither. With a
        single repository and no name reported, that repository.
        """
        if reported:
            try:
                return RepositoryRef.parse(reported).slug
            except ValueError:
                pass
            matches = [s for s in self.repositories if s.rsplit("/", 1)[-1] == reported]
            return matches[0] if len(matches) == 1 else None
        return self.repositories[0] if len(self.repositories) == 1 else None


@dataclass(frozen=True)
class CommitShipped:
    """A commit a run made. One sha, one owner: the earliest observation wins,
    ties broken by the smaller execution id, whatever order they arrive in."""

    sha: str
    execution_id: str
    workflow_id: str
    workflow_name: str
    repository: str
    committed_at: datetime


@dataclass(frozen=True)
class PullRequestOpened:
    """A PR a run created. Same rule as a commit: earliest ``created_at`` wins,
    then the smaller execution id."""

    repository: str
    number: int
    url: str
    execution_id: str
    workflow_id: str
    workflow_name: str
    created_at: datetime


@dataclass(frozen=True)
class PullRequestMerged:
    repository: str
    """The slug the forge names now; after a transfer, not the one the PR was opened in."""
    number: int
    merged_at: datetime
    repository_id: int | None = None
    """The forge's stable repository id, when the event carried one."""


@dataclass(frozen=True)
class ShippedDayRow:
    """One UTC day x repository x workflow of the rollup."""

    day: date
    repository: str
    workflow_id: str
    workflow_name: str
    commits: int = 0
    prs_opened: int = 0
    prs_merged: int = 0
    """Run PRs merged ON this day."""
    prs_opened_merged: int = 0
    """Run PRs opened on this day that have merged since (any later day)."""


@runtime_checkable
class ShippedLedger(Protocol):
    """Records shipped facts idempotently and serves the daily rollup."""

    async def record_commit(self, commit: CommitShipped) -> None: ...

    async def record_pull_request_opened(self, pr: PullRequestOpened) -> None: ...

    async def record_pull_request_merged(self, merge: PullRequestMerged) -> None: ...

    async def record_repository_alias(self, repository: str, repository_id: int) -> None:
        """``repository`` is (or was) the slug of the forge's repository ``repository_id``.

        How a PR opened under one slug is matched to its merge reported under
        another after a rename or transfer.
        """
        ...

    async def daily(
        self, start: date, end: date, workflow_id: str | None = None
    ) -> Sequence[ShippedDayRow]:
        """Rollup rows with ``start <= day <= end``, optionally one workflow's."""
        ...


@runtime_checkable
class ShippedLedgerProvider(Protocol):
    """A Lane 2 store that also keeps the shipped ledger.

    The observability writer the execution processor is given is the Lane 2
    store; when it can keep the ledger too, it says so by providing one. That
    keeps the ledger beside the telemetry it is derived from, with no second
    wiring path that could point it somewhere else.
    """

    @property
    def shipped_ledger(self) -> ShippedLedger: ...
