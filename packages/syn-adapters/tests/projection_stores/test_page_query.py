"""build_page_query: the shape of the one statement a list page costs (#967).

Whether it answers what ``PageQuery.run`` answers needs Postgres, and is
apps/syn-api/tests/integration/test_page_query_parity.py. These pin what needs
none: every filter is in the statement, values are bound rather than spliced,
and a field name that is not an identifier is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores.postgres_page import build_page_query
from syn_domain.projection_page import PageQuery, StatusOf

pytestmark = pytest.mark.unit

AFTER = datetime(2026, 10, 1, tzinfo=UTC)


def test_every_filter_and_the_page_are_in_the_one_statement() -> None:
    query = PageQuery(
        status=StatusOf.text("status"),
        timestamp_field="started_at",
        equals={"eval_id": "ev-1"},
        contains_all={"tags": frozenset({"b", "a"})},
        search="o'brien%",
        search_fields=("workflow_name",),
        statuses=frozenset({"failed"}),
        after=AFTER,
        offset=40,
        limit=20,
    )

    sql, params = build_page_query("proj_x", query, lean_ready=False)

    assert "data->>'eval_id' = $1" in sql
    assert "data->'tags' @> $2::text::jsonb" in sql
    assert "strpos(lower(data->>'workflow_name'), lower($3::text))" in sql
    assert "instant < $4::timestamptz" in sql
    assert "status = ANY($5::text[])" in sql
    assert "LIMIT 20 OFFSET 40" in sql
    assert "o'brien" not in sql
    assert params == ["ev-1", '["a", "b"]', "o'brien%", AFTER, ["failed"]]


def test_a_flag_status_and_a_lean_table_read_the_lean_document() -> None:
    query = PageQuery(
        status=StatusOf.flag("archived", if_true="archived", if_false="active"),
        timestamp_field="created_at",
    )

    sql, params = build_page_query("proj_evals", query, lean_ready=True)

    assert "CASE WHEN data->'archived' = 'true'::jsonb THEN 'archived' ELSE 'active' END" in sql
    assert "COALESCE(lean, data) AS data" in sql or "AS data FROM proj_evals" in sql
    assert "LIMIT" not in sql
    assert params == []


@pytest.mark.parametrize(
    "query",
    [
        PageQuery(status=StatusOf.text("status"), timestamp_field="at'; DROP TABLE x; --"),
        PageQuery(status=StatusOf.text("st atus"), timestamp_field="at"),
        PageQuery(
            status=StatusOf.text("status"),
            timestamp_field="at",
            search="x",
            search_fields=("name')",),
        ),
    ],
)
def test_a_field_that_is_not_an_identifier_is_refused(query: PageQuery) -> None:
    with pytest.raises(ValueError, match="unsafe page field"):
        build_page_query("proj_x", query, lean_ready=False)
