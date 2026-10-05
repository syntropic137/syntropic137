"""The eval and execution lists hand their whole page to the store (#967).

A store that implements ``page_keys`` is asked the WHOLE question - every
filter, the window, the page - and is never asked to scan the collection.
The store here answers with ``PageQuery.run`` over its documents, so these
pin what reaches the store and what the projection makes of the answer; the
Postgres answer is held to ``PageQuery.run`` by
apps/syn-api/tests/integration/test_page_query_parity.py.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from syn_domain.contexts.orchestration.slices.list_evals.projection import EvalListProjection
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)
from syn_domain.projection_page import PageQuery, StatusOf

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syn_domain.pagination import Page, ProjectionRecord
    from syn_domain.projection_count import GroupKey
    from syn_domain.projection_scan import JsonValue

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class _PagingStore:
    """Answers ``page_keys`` itself; refuses every read of a whole collection."""

    def __init__(self, docs: Mapping[str, Mapping[str, dict[str, JsonValue]]]) -> None:
        self._docs = docs
        self.queries: list[tuple[str, PageQuery]] = []
        self.reads: list[str] = []

    async def page_keys(self, projection: str, query: PageQuery) -> Page[str]:
        self.queries.append((projection, query))
        return query.run(
            self._docs[projection].items(), document_of=lambda kv: kv[1], to_row=lambda kv: kv[0]
        )

    async def get_many(self, projection: str, keys: Sequence[str]) -> dict[str, ProjectionRecord]:
        return {k: v for k, v in self._docs[projection].items() if k in keys}

    async def count_by(
        self,
        projection: str,
        fields: Sequence[str],
        *,
        filters: Mapping[str, object] | None = None,
    ) -> list[tuple[GroupKey, int]]:
        self.reads.append(f"count_by {projection} {tuple(fields)} {dict(filters or {})}")
        wanted = filters or {}
        groups = Counter(
            tuple(None if d.get(f) is None else str(d.get(f)) for f in fields)
            for d in self._docs[projection].values()
            if all(_holds(d.get(name), value) for name, value in wanted.items())
        )
        return list(groups.items())

    async def get_all(self, projection: str) -> list[dict[str, JsonValue]]:
        raise AssertionError(f"read every document of {projection}")

    async def query(self, projection: str, **_: object) -> list[dict[str, JsonValue]]:
        raise AssertionError(f"read whole documents of {projection}")


def _holds(stored: object, wanted: object) -> bool:
    if isinstance(wanted, (list, tuple)):
        return stored in wanted
    return stored == wanted


def _execution(n: int, eval_id: str | None, status: str) -> dict[str, JsonValue]:
    return {
        "workflow_execution_id": f"exec-{n}",
        "workflow_id": "wf",
        "workflow_name": "Nightly",
        "status": status,
        "started_at": f"2026-10-0{n}T00:00:00+00:00",
        "tags": ["gate"] if n % 2 else [],
        "eval_id": eval_id,
    }


def _eval(eval_id: str, *, archived: bool, day: int) -> dict[str, JsonValue]:
    return {
        "eval_id": eval_id,
        "name": f"Eval {eval_id}",
        "goal": "ship it",
        "starting_workflow_id": "wf",
        "baseline_repos": [],
        "tags": ["nightly"],
        "frozen": False,
        "archived": archived,
        "created_at": f"2026-10-0{day}T00:00:00+00:00",
        "updated_at": f"2026-10-0{day}T00:00:00+00:00",
    }


EXECUTIONS = {
    f"exec-{n}": _execution(n, eval_id, status)
    for n, eval_id, status in [
        (1, "ev-a", "completed"),
        (2, "ev-a", "failed"),
        (3, "ev-a", "completed"),
        (4, "ev-b", "running"),
        (5, None, "completed"),
    ]
}
EVALS = {
    "ev-a": _eval("ev-a", archived=False, day=2),
    "ev-b": _eval("ev-b", archived=True, day=3),
    "ev-c": _eval("ev-c", archived=False, day=1),
}


async def test_the_executions_page_hands_every_filter_and_the_page_to_the_store() -> None:
    store = _PagingStore({"workflow_executions": EXECUTIONS})
    after = datetime(2026, 10, 2, tzinfo=UTC)

    page = await WorkflowExecutionListProjection(store).page(  # type: ignore[arg-type]
        statuses=["completed"],
        started_after=after,
        search="exec",
        tags=["gate"],
        eval_id="ev-a",
        offset=0,
        limit=1,
    )

    assert store.queries == [
        (
            "workflow_executions",
            PageQuery(
                status=StatusOf.text("status"),
                timestamp_field="started_at",
                equals={"eval_id": "ev-a"},
                contains_all={"tags": frozenset({"gate"})},
                search="exec",
                search_fields=("workflow_execution_id", "workflow_id", "workflow_name"),
                statuses=frozenset({"completed"}),
                after=after,
                before=None,
                offset=0,
                limit=1,
            ),
        )
    ]
    assert store.reads == []
    assert [row.workflow_execution_id for row in page.rows] == ["exec-3"]
    assert page.total == 1
    assert page.status_counts == {"completed": 1}


async def test_the_eval_page_is_one_store_query_and_one_tally_read_for_all_its_rows() -> None:
    store = _PagingStore({"evals": EVALS, "workflow_executions": EXECUTIONS})

    page = await EvalListProjection(store).page(limit=10)  # type: ignore[arg-type]

    assert [projection for projection, _ in store.queries] == ["evals"]
    _, query = store.queries[0]
    assert query.status == StatusOf.flag("archived", if_true="archived", if_false="active")
    # The tallies are grouped by the store: counts leave it, member rows do not.
    assert store.reads == [
        "count_by workflow_executions ('eval_id', 'status') {'eval_id': ['ev-a', 'ev-b', 'ev-c']}"
    ]
    by_id = {row.record.eval_id: row for row in page.rows}
    assert [row.record.eval_id for row in page.rows] == ["ev-b", "ev-a", "ev-c"]
    assert by_id["ev-a"].run_count == 3
    assert by_id["ev-a"].run_status_counts == {"completed": 2, "failed": 1}
    assert by_id["ev-b"].run_status_counts == {"running": 1}
    assert by_id["ev-c"].run_count == 0
    assert by_id["ev-c"].run_status_counts == {}
    assert page.status_counts == {"active": 2, "archived": 1}


async def test_the_eval_page_filters_status_tags_and_search_in_the_store_query() -> None:
    store = _PagingStore({"evals": EVALS, "workflow_executions": EXECUTIONS})

    page = await EvalListProjection(store).page(  # type: ignore[arg-type]
        statuses=["active"], search="EV-A", tags=["nightly"], limit=5
    )

    _, query = store.queries[0]
    assert (query.search, query.search_fields) == ("EV-A", ("eval_id", "name", "goal"))
    assert query.contains_all == {"tags": frozenset({"nightly"})}
    assert query.statuses == frozenset({"active"})
    assert [row.record.eval_id for row in page.rows] == ["ev-a"]
    assert page.total == 1
    assert page.status_counts == {"active": 1}


async def test_a_flag_status_reads_only_true_as_the_true_label() -> None:
    status = StatusOf.flag("archived", if_true="archived", if_false="active")

    assert [status.of({"archived": v}) for v in (True, False, None)] == [
        "archived",
        "active",
        "active",
    ]
    assert StatusOf.text("status").of({}) == ""
