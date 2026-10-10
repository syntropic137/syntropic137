"""The shipped ledger in memory: test/offline only (ADR-060).

The same semantics as ``PostgresShippedLedger``, held in dicts: idempotent by
identity, order-independent between a PR and its merge. The contract tests
run both against the same cases, so this is also the readable statement of
what the SQL must do.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from syn_adapters.in_memory import InMemoryAdapter
from syn_domain.contexts.orchestration import ShippedDayRow, repository_key, utc_day

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from syn_domain.contexts.orchestration import (
        CommitShipped,
        PullRequestMerged,
        PullRequestOpened,
    )

type _RowKey = tuple[date, str, str]
type _PrKey = tuple[str, int]


@dataclass(frozen=True)
class _RunPr:
    repository: str
    workflow_id: str
    workflow_name: str
    opened_day: date


class InMemoryShippedLedger(InMemoryAdapter):
    """``ShippedLedger`` in memory."""

    def __init__(self) -> None:
        super().__init__()
        self._commits: set[str] = set()
        self._prs: dict[_PrKey, _RunPr] = {}
        self._merges: dict[_PrKey, datetime] = {}
        self._rows: dict[_RowKey, ShippedDayRow] = {}

    def _bump(self, day: date, repository: str, workflow_id: str, name: str, column: str) -> None:
        key = (day, repository_key(repository), workflow_id)
        row = self._rows.get(key) or ShippedDayRow(day, repository, workflow_id, name)
        row = replace(row, workflow_name=name or row.workflow_name)
        self._rows[key] = replace(row, **{column: getattr(row, column) + 1})

    async def record_commit(self, commit: CommitShipped) -> None:
        if commit.sha in self._commits:
            return
        self._commits.add(commit.sha)
        self._bump(
            utc_day(commit.committed_at),
            commit.repository,
            commit.workflow_id,
            commit.workflow_name,
            "commits",
        )

    async def record_pull_request_opened(self, pr: PullRequestOpened) -> None:
        key = (repository_key(pr.repository), pr.number)
        if key in self._prs:
            return
        run_pr = _RunPr(pr.repository, pr.workflow_id, pr.workflow_name, utc_day(pr.created_at))
        self._prs[key] = run_pr
        self._bump(run_pr.opened_day, *self._who(run_pr), "prs_opened")
        merged_at = self._merges.get(key)
        if merged_at is not None:
            self._count_merge(run_pr, merged_at)

    async def record_pull_request_merged(self, merge: PullRequestMerged) -> None:
        key = (repository_key(merge.repository), merge.number)
        if key in self._merges:
            return
        self._merges[key] = merge.merged_at
        run_pr = self._prs.get(key)
        if run_pr is not None:
            self._count_merge(run_pr, merge.merged_at)

    def _count_merge(self, run_pr: _RunPr, merged_at: datetime) -> None:
        self._bump(run_pr.opened_day, *self._who(run_pr), "prs_opened_merged")
        self._bump(utc_day(merged_at), *self._who(run_pr), "prs_merged")

    @staticmethod
    def _who(run_pr: _RunPr) -> tuple[str, str, str]:
        return (run_pr.repository, run_pr.workflow_id, run_pr.workflow_name)

    async def daily(
        self, start: date, end: date, workflow_id: str | None = None
    ) -> Sequence[ShippedDayRow]:
        return [
            row
            for key, row in sorted(self._rows.items())
            if start <= row.day <= end and (workflow_id is None or row.workflow_id == workflow_id)
        ]
