"""The conversation index reports what ran as ``model`` and the alias apart (ADR-067).

Rows indexed before ADR-067 filed the phase's REQUESTED model - often an alias
such as ``opus`` - under ``model``. Reading one back must report that alias as
``requested_model`` and the model that ran as unknown, while rows written since
keep both fields as written.
"""

from __future__ import annotations

import pytest

from syn_adapters.conversations import SessionContext
from syn_adapters.conversations.minio_index import (
    ADD_REQUESTED_MODEL_COLUMN_SQL,
    index_row_model,
    insert_index,
)
from syn_shared.agents import ModelAlias, ModelId

pytestmark = pytest.mark.unit


class TestReadingTheIndex:
    def test_a_legacy_alias_row_is_a_request_not_a_model(self) -> None:
        row = index_row_model(ModelAlias.OPUS, None)
        assert row.observed is None
        assert row.requested == ModelAlias.OPUS

    def test_a_legacy_explicit_id_is_kept_as_what_ran(self) -> None:
        row = index_row_model(ModelId.CLAUDE_OPUS_5_5, None)
        assert row.observed == ModelId.CLAUDE_OPUS_5_5
        assert row.requested is None

    def test_a_new_row_is_read_as_written(self) -> None:
        row = index_row_model(ModelId.CLAUDE_OPUS_5_5, ModelAlias.OPUS)
        assert row.observed == ModelId.CLAUDE_OPUS_5_5
        assert row.requested == ModelAlias.OPUS

    def test_a_new_row_whose_harness_never_said_stays_unknown(self) -> None:
        row = index_row_model(None, ModelAlias.OPUS)
        assert row.observed is None
        assert row.requested == ModelAlias.OPUS


class _Conn:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, sql: str, *args: object) -> None:
        self.executed.append((sql, args))


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Pool:
    def __init__(self) -> None:
        self.conn = _Conn()

    def acquire(self) -> _Acquire:
        return _Acquire(self.conn)


class TestWritingTheIndex:
    def test_the_context_carries_both(self) -> None:
        context = SessionContext(model=ModelId.CLAUDE_OPUS_5_5, requested_model=ModelAlias.OPUS)
        assert context.to_dict()["model"] == ModelId.CLAUDE_OPUS_5_5
        assert context.to_dict()["requested_model"] == ModelAlias.OPUS

    async def test_the_request_is_stored_when_the_column_exists(self) -> None:
        pool = _Pool()
        context = SessionContext(model=ModelId.CLAUDE_OPUS_5_5, requested_model=ModelAlias.OPUS)
        await insert_index(pool, "s1", "k", 1, context, "b", with_requested_model=True)  # type: ignore[arg-type]

        [(sql, args)] = pool.conn.executed
        assert "requested_model" in sql
        assert args[-1] == ModelAlias.OPUS
        assert ModelId.CLAUDE_OPUS_5_5 in args

    async def test_without_the_column_the_row_is_still_indexed(self) -> None:
        """A deployment that has not migrated loses the request, never the row."""
        pool = _Pool()
        context = SessionContext(model=ModelId.CLAUDE_OPUS_5_5, requested_model=ModelAlias.OPUS)
        await insert_index(pool, "s1", "k", 1, context, "b", with_requested_model=False)  # type: ignore[arg-type]

        [(sql, args)] = pool.conn.executed
        assert "requested_model" not in sql
        assert ModelAlias.OPUS not in args

    def test_the_migration_is_idempotent(self) -> None:
        assert "ADD COLUMN IF NOT EXISTS requested_model" in ADD_REQUESTED_MODEL_COLUMN_SQL
