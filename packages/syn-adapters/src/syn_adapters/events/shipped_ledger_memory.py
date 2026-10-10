"""The shipped ledger in memory: test/offline only (ADR-060).

The same semantics as ``PostgresShippedLedger``, as plainly as they can be
written: facts kept by identity, the earliest claim owning each, merges
matched under any slug of the same repository id, and the rollup computed
from the facts every time it is read. The contract tests run both ledgers
against the same cases, so this is the readable statement of what the SQL
must do.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from syn_adapters.in_memory import InMemoryAdapter
from syn_domain.contexts.orchestration import ShippedDayRow, repository_key, utc_day

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from syn_domain.contexts.orchestration import (
        CommitShipped,
        PullRequestMerged,
        PullRequestOpened,
    )

type _PrKey = tuple[str, int]
type _RowKey = tuple[date, str, str]


def _aware(instant: datetime) -> datetime:
    return instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)


@dataclass
class _Totals:
    repository: str = ""
    workflow_name: str = ""
    commits: int = 0
    prs_opened: int = 0
    prs_merged: int = 0
    prs_opened_merged: int = 0

    def note(self, repository: str, workflow_name: str) -> None:
        self.repository = min(filter(None, (self.repository, repository)))
        self.workflow_name = max(self.workflow_name, workflow_name)


class InMemoryShippedLedger(InMemoryAdapter):
    """``ShippedLedger`` in memory."""

    def __init__(self) -> None:
        super().__init__()
        self._commits: dict[str, CommitShipped] = {}
        self._prs: dict[_PrKey, PullRequestOpened] = {}
        self._merges: dict[_PrKey, PullRequestMerged] = {}
        self._aliases: dict[str, int] = {}

    async def record_commit(self, commit: CommitShipped) -> None:
        old = self._commits.get(commit.sha)
        if old is None or (_aware(commit.committed_at), commit.execution_id) < (
            _aware(old.committed_at),
            old.execution_id,
        ):
            self._commits[commit.sha] = commit

    async def record_pull_request_opened(self, pr: PullRequestOpened) -> None:
        key = (repository_key(pr.repository), pr.number)
        old = self._prs.get(key)
        if old is None or (_aware(pr.created_at), pr.execution_id) < (
            _aware(old.created_at),
            old.execution_id,
        ):
            self._prs[key] = pr

    async def record_pull_request_merged(self, merge: PullRequestMerged) -> None:
        key = (repository_key(merge.repository), merge.number)
        if key in self._merges:
            return
        self._merges[key] = merge
        if merge.repository_id is not None:
            await self.record_repository_alias(merge.repository, merge.repository_id)

    async def record_repository_alias(self, repository: str, repository_id: int) -> None:
        self._aliases.setdefault(repository_key(repository), repository_id)

    def _merge_of(self, key: _PrKey) -> datetime | None:
        """The merge of a run PR: under its own slug, or any slug of the same id."""
        repo, number = key
        alias = self._aliases.get(repo)
        found = [
            m.merged_at
            for (m_repo, m_number), m in self._merges.items()
            if m_number == number
            and (m_repo == repo or (alias is not None and m.repository_id == alias))
        ]
        return min(found, key=_aware) if found else None

    async def daily(
        self, start: date, end: date, workflow_id: str | None = None
    ) -> Sequence[ShippedDayRow]:
        totals: dict[_RowKey, _Totals] = defaultdict(_Totals)
        for c in self._commits.values():
            row = totals[(utc_day(c.committed_at), repository_key(c.repository), c.workflow_id)]
            row.commits += 1
            row.note(c.repository, c.workflow_name)
        for key, pr in self._prs.items():
            who = (repository_key(pr.repository), pr.workflow_id)
            opened = totals[(utc_day(pr.created_at), *who)]
            opened.prs_opened += 1
            opened.note(pr.repository, pr.workflow_name)
            merged_at = self._merge_of(key)
            if merged_at is not None:
                opened.prs_opened_merged += 1
                merged = totals[(utc_day(merged_at), *who)]
                merged.prs_merged += 1
                merged.note(pr.repository, pr.workflow_name)
        return [
            ShippedDayRow(
                day=day,
                repository=t.repository,
                workflow_id=wf,
                workflow_name=t.workflow_name,
                commits=t.commits,
                prs_opened=t.prs_opened,
                prs_merged=t.prs_merged,
                prs_opened_merged=t.prs_opened_merged,
            )
            for (day, _, wf), t in sorted(totals.items())
            if start <= day <= end and (workflow_id is None or wf == workflow_id)
        ]
