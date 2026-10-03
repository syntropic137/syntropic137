"""The conversation index gains ``requested_model`` on a pre-ADR-067 table.

Against real Postgres, because the unit tests only see the SQL text: this
starts from the table as migration 003 created it, lets the adapter add the
column the way it does at startup, and round-trips a row written before and a
row written after through the real reader.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from syn_adapters.conversations import SessionContext
from syn_adapters.conversations.minio_index import (
    ensure_requested_model_column,
    get_session_metadata,
    insert_index,
)
from syn_shared.agents import ModelAlias, ModelId

_STARTED = datetime(2026, 9, 24, tzinfo=UTC)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_MIGRATION_003 = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "syn_adapters"
    / "projection_stores"
    / "migrations"
    / "003_session_conversations.sql"
)


@pytest.fixture
async def pool(test_infrastructure):
    import asyncpg

    pool = await asyncpg.create_pool(test_infrastructure.timescaledb_url, min_size=1, max_size=2)
    async with pool.acquire() as conn:
        await conn.execute(_MIGRATION_003.read_text())
    yield pool
    await pool.close()


async def test_the_column_is_added_and_both_eras_read_back(pool) -> None:
    assert await ensure_requested_model_column(pool, auto_create=True) is True
    # Idempotent: a second startup changes nothing and still says yes.
    assert await ensure_requested_model_column(pool, auto_create=True) is True

    legacy_id = f"sess-legacy-{uuid4()}"
    new_id = f"sess-new-{uuid4()}"
    await insert_index(
        pool,
        legacy_id,
        "k",
        1,
        SessionContext(model=ModelAlias.OPUS, started_at=_STARTED),
        "b",
        with_requested_model=False,
    )
    await insert_index(
        pool,
        new_id,
        "k",
        1,
        SessionContext(
            model=ModelId.CLAUDE_OPUS_5_5, requested_model=ModelAlias.OPUS, started_at=_STARTED
        ),
        "b",
        with_requested_model=True,
    )

    legacy = await get_session_metadata(pool, legacy_id)
    new = await get_session_metadata(pool, new_id)
    assert legacy is not None
    assert new is not None
    assert (legacy["model"], legacy["requested_model"]) == (None, ModelAlias.OPUS)
    assert (new["model"], new["requested_model"]) == (ModelId.CLAUDE_OPUS_5_5, ModelAlias.OPUS)


async def test_a_restored_session_refreshes_its_model(pool) -> None:
    await ensure_requested_model_column(pool, auto_create=True)
    session_id = f"sess-{uuid4()}"
    for model in (None, ModelId.CLAUDE_OPUS_5_5):
        await insert_index(
            pool,
            session_id,
            "k",
            1,
            SessionContext(model=model, requested_model=ModelAlias.OPUS, started_at=_STARTED),
            "b",
            with_requested_model=True,
        )
    row = await get_session_metadata(pool, session_id)
    assert row is not None
    assert row["model"] == ModelId.CLAUDE_OPUS_5_5
