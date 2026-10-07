"""build_page_query: the shape of the one statement a list page costs (#967).

Whether it answers what ``PageQuery.run`` answers needs Postgres, and is
apps/syn-api/tests/integration/test_page_query_parity.py. These pin what needs
none: every filter is in the statement, values are bound rather than spliced,
and a field name that is not an identifier is refused.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from syn_adapters.projection_stores.postgres_page_keys import (
    _ISO_TIMESTAMP,
    _folds,
    build_page_query,
    instant_sql,
)
from syn_domain.pagination import coerce_datetime
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
    assert "unnest($4::text[], $5::text[])" in sql
    assert "$3::text) > 0" in sql
    # In the scan's WHERE, on the expression the window index is built on.
    assert f"{instant_sql('started_at')} >= $6::timestamptz" in sql
    assert "status = ANY($7::text[])" in sql
    assert "LIMIT 20 OFFSET 40" in sql
    assert "o'brien" not in sql
    assert params[:3] == ["ev-1", '["a", "b"]', "o'brien%"]
    assert params[5:] == [AFTER, ["failed"]]


@pytest.mark.parametrize("text", ["Straße", "ΣΊΣΥΦΟΣ", "ﬁle", "İstanbul", "plain ASCII"])
def test_the_fold_table_is_casefold_one_character_at_a_time(text: str) -> None:
    # The SQL fold maps each character through this table, so applied the
    # same way here it has to be ``casefold`` itself, or search drifts.
    sources, targets = _folds()
    table = dict(zip(sources, targets, strict=True))
    assert "".join(table.get(c, c) for c in text) == text.casefold()


@pytest.mark.parametrize(
    ("stamp", "readable"),
    [
        ("2026-10-01T10:00:00Z", True),
        ("2026-10-01T10:00:00.123456+05:30", True),
        ("2026-10-01 10:00", True),
        ("2026-10-01", True),
        ("2026-10-01T24:00:00Z", False),
        ("2026-10-01T23:59:60Z", False),
        ("2026-10-01T23:60:00", False),
        ("2026-10-01T10:00:00+24:00", False),
        ("not a date", False),
    ],
)
def test_the_timestamp_gate_lets_through_only_what_python_reads(stamp: str, readable: bool) -> None:
    # PostgreSQL reads 24:00 and :60, Python does not; the gate keeps them
    # undated on both sides. Impossible days (02-30) are pg_input_is_valid's.
    assert (re.match(_ISO_TIMESTAMP, stamp) is not None) is readable
    assert (coerce_datetime(stamp) is not None) is readable


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
