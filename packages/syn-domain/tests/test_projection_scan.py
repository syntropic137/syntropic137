"""paginate_projection: the field scan answers what the full read answered (E2).

The Postgres half is held to parity end to end by
apps/syn-api/tests/integration/test_list_detail_parity.py. These pin the parts
that need no database: the fallback, the field guard, and a row that vanishes
between the two reads.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest

from syn_domain import agent_event_span
from syn_domain.agent_event_span import EventSpan
from syn_domain.pagination import Page, ProjectionRecord, matches_search, paginate
from syn_domain.projection_scan import (
    Decide,
    JsonValue,
    ListShape,
    RowDecision,
    ScannedRecord,
    SqlPage,
    SqlPageRequest,
    UndeclaredFieldError,
    UnjudgedRow,
    WindowPlacement,
    page_projection,
    paginate_projection,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

DOCS: list[dict[str, JsonValue]] = [
    {"id": f"s{n}", "status": ("ok", "bad")[n % 2], "at": f"2026-10-0{n % 9 + 1}", "body": "x" * n}
    for n in range(12)
]


class _ScanningStore:
    def __init__(self, docs: list[dict[str, JsonValue]], *, lose: str | None = None) -> None:
        self._docs = docs
        self._lose = lose
        self.scanned_fields: list[str] = []

    async def scan_fields(
        self,
        projection: str,
        fields: Sequence[str],
        *,
        filters: Mapping[str, str] | None = None,
        order_by: str | None = None,
    ) -> list[tuple[str, Mapping[str, JsonValue]]]:
        self.scanned_fields = list(fields)
        return [(str(d["id"]), {f: d.get(f) for f in fields}) for d in self._docs]

    async def get_many(self, projection: str, keys: Sequence[str]) -> dict[str, ProjectionRecord]:
        return {str(d["id"]): d for d in self._docs if d["id"] in keys and d["id"] != self._lose}


async def _page(store: object, fields: tuple[str, ...], offset: int = 0) -> Page[str]:
    async def full_read() -> list[dict[str, JsonValue]]:
        return DOCS

    return await paginate_projection(
        store,
        "p",
        fields=fields,
        filters=None,
        order_by=None,
        full_read=full_read,
        base_predicate=lambda r: matches_search("s1", r.get("id")),
        status_of=lambda r: str(r.get("status") or ""),
        statuses=["ok"],
        timestamp_of=lambda r: r.get("at"),
        after=None,
        before=None,
        to_row=lambda r: f"{r['id']}:{len(str(r['body']))}",
        offset=offset,
        limit=3,
    )


def _expected(offset: int = 0) -> Page[str]:
    return paginate(
        DOCS,
        base_predicate=lambda r: matches_search("s1", r.get("id")),
        status_of=lambda r: str(r.get("status") or ""),
        statuses=["ok"],
        timestamp_of=lambda r: r.get("at"),
        to_row=lambda r: f"{r['id']}:{len(str(r['body']))}",
        offset=offset,
        limit=3,
    )


async def test_the_scan_answers_what_the_full_read_answered() -> None:
    store = _ScanningStore(DOCS)
    for offset in (0, 1, 3):
        assert await _page(store, ("id", "status", "at"), offset) == _expected(offset)
    assert "body" not in store.scanned_fields


async def test_a_store_that_cannot_scan_gets_the_full_read() -> None:
    assert await _page(object(), ("id",)) == _expected()


async def test_a_predicate_reading_an_unscanned_field_fails_loudly() -> None:
    with pytest.raises(UndeclaredFieldError, match="'at'"):
        await _page(_ScanningStore(DOCS), ("id", "status"))


def test_a_scanned_record_refuses_both_spellings_of_an_undeclared_read() -> None:
    record = ScannedRecord(frozenset({"id"}), {"id": "a", "other": 1})
    assert record.get("id") == "a"
    with pytest.raises(UndeclaredFieldError):
        record.get("other")
    with pytest.raises(UndeclaredFieldError):
        _ = record["other"]


async def test_a_row_deleted_between_the_reads_is_dropped_not_invented() -> None:
    expected = _expected()
    lost = expected.rows[0].split(":")[0]
    page = await _page(_ScanningStore(DOCS, lose=lost), ("id", "status", "at"))
    assert page.rows == expected.rows[1:]
    assert page.total == expected.total


def test_an_unbounded_span_admits_every_timestamp() -> None:
    span = EventSpan.unbounded()
    assert span.lower.year == 1
    assert span.upper.year == 9999


class _RollupConn:
    def __init__(self, first: date | None, last: date | None) -> None:
        self.row = {"first_day": first, "last_day": last}
        self.calls = 0

    async def fetch(self, query: str, /, *args: object) -> list[dict[str, date | None]]:
        self.calls += 1
        assert "agent_event_day_rollup" in query
        return [self.row]


async def test_a_span_covers_its_last_day_whole() -> None:
    conn = _RollupConn(date(2026, 10, 1), date(2026, 10, 3))
    span = await agent_event_span.for_executions(conn, ["e"])
    assert span.lower == datetime(2026, 10, 1, tzinfo=UTC)
    assert span.upper == datetime(2026, 10, 4, tzinfo=UTC)
    assert span.lower <= datetime(2026, 10, 3, 23, 59, 59, 999999, tzinfo=UTC) < span.upper


async def test_an_id_the_rollup_has_not_seen_reads_unbounded() -> None:
    assert await agent_event_span.for_sessions(_RollupConn(None, None), ["s"]) == (
        EventSpan.unbounded()
    )


async def test_no_ids_asks_nothing() -> None:
    conn = _RollupConn(None, None)
    assert await agent_event_span.for_sessions(conn, []) == EventSpan.unbounded()
    assert conn.calls == 0


SHAPE = ListShape(timestamp_field="at", facet_field="status", search_fields=("id",))


async def _shaped(store: object, *, search: str | None = "s1") -> Page[str]:
    async def full_read() -> list[dict[str, JsonValue]]:
        return DOCS

    return await page_projection(
        store,
        "p",
        shape=SHAPE,
        filters=None,
        search=search,
        statuses=["ok"],
        after=None,
        before=None,
        full_read=full_read,
        to_row=lambda r: f"{r['id']}:{len(str(r['body']))}",
        offset=0,
        limit=3,
    )


async def test_a_shaped_page_without_sql_is_paginate() -> None:
    assert await _shaped(object()) == _expected()
    assert await _shaped(_ScanningStore(DOCS)) == _expected()


class _SqlStore:
    """Hands every row to ``decide``, as Postgres does for rows it cannot judge."""

    def __init__(self) -> None:
        self.request: SqlPageRequest | None = None
        self.decisions: list[RowDecision] = []

    async def page_in_sql(
        self, projection: str, request: SqlPageRequest, decide: Decide
    ) -> SqlPage:
        self.request = request
        self.decisions = decide(
            [UnjudgedRow(str(d["id"]), {f: d.get(f) for f in SHAPE.fields}) for d in DOCS]
        )
        return SqlPage(rows=[DOCS[0]], total=1, status_counts={"ok": 1}, excluded_undated=0)


async def test_rows_sql_cannot_judge_are_judged_by_paginates_own_predicates() -> None:
    store = _SqlStore()
    page = await _shaped(store, search="S1")
    assert page == Page(rows=["s0:0"], total=1, status_counts={"ok": 1})
    assert store.request is not None
    assert store.request.needle == "s1"
    assert store.request.statuses == frozenset({"ok"})
    by_key = {d.key: d for d in store.decisions}
    assert by_key["s1"].matched and by_key["s10"].matched and not by_key["s2"].matched
    assert by_key["s3"].facet == "bad"
    assert by_key["s3"].sort_key == "2026-10-04"
    assert all(d.placement is WindowPlacement.INSIDE for d in store.decisions)
