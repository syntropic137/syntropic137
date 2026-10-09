"""Queries over the workflow execution list read model (#967).

The ``workflow_executions`` read model is written by the ``list_executions``
slice and read by two: that slice's own list view, and ``list_evals``, whose
Eval detail is a page of member executions and whose Eval list tallies each
Eval's runs. Slices may not import one another, so the read side lives here
and both import it. The writes stay in ``list_executions``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)
from syn_domain.projection_count import count_by
from syn_domain.projection_page import PageQuery, StatusOf, page_projection

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import datetime

    from event_sourcing import ProjectionStore

    from syn_domain.pagination import Page

WORKFLOW_EXECUTIONS = "workflow_executions"


class ExecutionListReads:
    """Reads the workflow execution list read model; writes nothing."""

    _store: ProjectionStore

    def __init__(self, store: ProjectionStore):
        self._store = store

    async def page(
        self,
        *,
        statuses: Collection[str] | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        search: str | None = None,
        tags: Collection[str] | None = None,
        eval_id: str | None = None,
        in_eval: bool | None = None,
        workflow_id: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Page[WorkflowExecutionSummary]:
        """One page of executions, with the total and status facets it came from.

        `total` used to come from a store-level `COUNT(*)` while the rows were
        filtered in Python (#1119). The two spelled the same predicate twice and
        agreed only by luck: adding the time window here would have left `total`
        counting the whole collection, so a 24-hour view reported the size of
        all history. Rows, total and facets now come from one filtered
        sequence and cannot drift.

        `search` matches case-insensitively against the execution id, the
        workflow id and the workflow name.

        `tags` keeps only executions carrying EVERY tag given (AND), matched
        against their current tags (#967). Pass them normalised: this compares
        exactly, so the caller validates through `TagSet` first.

        `eval_id` keeps only the Eval's current members (#967), which makes
        this the Eval's runs view too. It is handed to the store as a filter,
        so it is applied in the query rather than over every execution.

        `in_eval` keeps only executions in some Eval (`True`) or in none
        (`False`), so eval runs can be shown apart from every other run.

        `workflow_id` keeps only that workflow's executions, applied in the
        query like `eval_id` (#1788: the workflow trend).
        """
        equals: dict[str, str] = {} if eval_id is None else {"eval_id": eval_id}
        if workflow_id is not None:
            equals["workflow_id"] = workflow_id
        query = PageQuery(
            status=StatusOf.text("status"),
            timestamp_field="started_at",
            equals=equals,
            present={} if in_eval is None else {"eval_id": in_eval},
            contains_all={"tags": frozenset(tags or ())},
            search=search,
            search_fields=("workflow_execution_id", "workflow_id", "workflow_name"),
            statuses=frozenset(statuses) if statuses else None,
            after=started_after,
            before=started_before,
            offset=offset,
            limit=limit,
            key_field="workflow_execution_id",
        )
        return await page_projection(
            self._store,
            WORKFLOW_EXECUTIONS,
            query,
            to_row=lambda record: WorkflowExecutionSummary.from_dict(dict(record)),
        )

    async def get_by_id(self, execution_id: str) -> WorkflowExecutionSummary | None:
        """One execution's row, or None when the list has not projected it."""
        data = await self._store.get(WORKFLOW_EXECUTIONS, execution_id)
        if data:
            return WorkflowExecutionSummary.from_dict(data)
        return None

    async def members_of(
        self, eval_ids: Collection[str]
    ) -> dict[str, list[WorkflowExecutionSummary]]:
        """Each Eval's current member executions, in one read, unordered (#1811).

        Every id given gets an entry, empty when it has no members. The same
        rows ``page(eval_id=...)`` pages for each id, without a query per Eval.
        """
        members: dict[str, list[WorkflowExecutionSummary]] = {eval_id: [] for eval_id in eval_ids}
        if not members:
            return members
        documents = await self._store.query(
            WORKFLOW_EXECUTIONS, filters={"eval_id": sorted(members)}
        )
        for document in documents:
            row = WorkflowExecutionSummary.from_dict(dict(document))
            if row.eval_id is not None and row.eval_id in members:
                members[row.eval_id].append(row)
        return members

    async def run_tallies(self, eval_ids: Collection[str]) -> dict[str, dict[str, int]]:
        """Each Eval's current member executions tallied by status, in one read.

        Every id given gets an entry, empty when it has no members. Answers
        what ``page(eval_id=..., limit=0).status_counts`` answers for each id,
        without a query per Eval.
        """
        tallies: dict[str, dict[str, int]] = {eval_id: {} for eval_id in eval_ids}
        if not tallies:
            return tallies
        # Grouped in the store: only (eval, status, count) leaves the database,
        # never a row per member execution.
        groups = await count_by(
            self._store,
            WORKFLOW_EXECUTIONS,
            ("eval_id", "status"),
            filters={"eval_id": sorted(tallies)},
        )
        for (eval_id, status), count in groups.items():
            tally = tallies.get(str(eval_id))
            if tally is not None:
                key = status or ""
                tally[key] = tally.get(key, 0) + count
        return tallies
