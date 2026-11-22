"""Tests for RepoCostProjection."""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from syn_adapters.projection_stores import InMemoryProjectionStore
from syn_domain.contexts.organization.slices.repo_cost.projection import (
    RepoCostProjection,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def _seed_correlation(
    store: InMemoryProjectionStore, repo: str, exec_id: str, wf_id: str = "wf-1"
) -> None:
    key = f"{exec_id}:{repo}"
    await store.save(
        "repo_correlation",
        key,
        {
            "repo_full_name": repo,
            "execution_id": exec_id,
            "workflow_id": wf_id,
            "correlation_source": "trigger",
            "correlated_at": "2026-03-06T10:00:00",
        },
    )


@pytest.mark.unit
class TestRepoCostProjection:
    @pytest.mark.asyncio
    async def test_completed_records_cost(self) -> None:
        store = InMemoryProjectionStore()
        proj = RepoCostProjection(store)
        await _seed_correlation(store, "acme/api", "exec-1")

        await proj.on_workflow_completed(
            {
                "execution_id": "exec-1",
                "workflow_id": "wf-1",
                "total_cost_usd": "5.00",
                "total_tokens": 10000,
                "total_input_tokens": 8000,
                "total_output_tokens": 2000,
            }
        )

        cost = await proj.get_cost("acme/api")
        assert cost.total_cost_usd == Decimal("5.00")
        assert cost.total_tokens == 10000
        assert cost.total_input_tokens == 8000
        assert cost.total_output_tokens == 2000
        assert cost.execution_count == 1

    @pytest.mark.asyncio
    async def test_failed_also_records_cost(self) -> None:
        store = InMemoryProjectionStore()
        proj = RepoCostProjection(store)
        await _seed_correlation(store, "acme/api", "exec-2")

        await proj.on_workflow_failed(
            {
                "execution_id": "exec-2",
                "workflow_id": "wf-1",
                "total_cost_usd": "2.00",
                "total_tokens": 3000,
                "total_input_tokens": 2000,
                "total_output_tokens": 1000,
            }
        )

        cost = await proj.get_cost("acme/api")
        assert cost.total_cost_usd == Decimal("2.00")
        assert cost.execution_count == 1

    @pytest.mark.asyncio
    async def test_cost_accumulates_across_executions(self) -> None:
        store = InMemoryProjectionStore()
        proj = RepoCostProjection(store)
        await _seed_correlation(store, "acme/api", "exec-1")
        await _seed_correlation(store, "acme/api", "exec-2")

        await proj.on_workflow_completed(
            {
                "execution_id": "exec-1",
                "workflow_id": "wf-1",
                "total_cost_usd": "3.00",
                "total_tokens": 1000,
                "total_input_tokens": 800,
                "total_output_tokens": 200,
            }
        )
        await proj.on_workflow_completed(
            {
                "execution_id": "exec-2",
                "workflow_id": "wf-1",
                "total_cost_usd": "7.00",
                "total_tokens": 2000,
                "total_input_tokens": 1500,
                "total_output_tokens": 500,
            }
        )

        cost = await proj.get_cost("acme/api")
        assert cost.total_cost_usd == Decimal("10.00")
        assert cost.total_tokens == 3000
        assert cost.execution_count == 2

    @pytest.mark.asyncio
    async def test_cost_by_workflow_breakdown(self) -> None:
        store = InMemoryProjectionStore()
        proj = RepoCostProjection(store)
        await _seed_correlation(store, "acme/api", "exec-1", "wf-deploy")
        await _seed_correlation(store, "acme/api", "exec-2", "wf-test")

        await proj.on_workflow_completed(
            {
                "execution_id": "exec-1",
                "workflow_id": "wf-deploy",
                "total_cost_usd": "5.00",
                "total_tokens": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
            }
        )
        await proj.on_workflow_completed(
            {
                "execution_id": "exec-2",
                "workflow_id": "wf-test",
                "total_cost_usd": "2.00",
                "total_tokens": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
            }
        )

        cost = await proj.get_cost("acme/api")
        assert cost.cost_by_workflow["wf-deploy"] == Decimal("5.00")
        assert cost.cost_by_workflow["wf-test"] == Decimal("2.00")

    @pytest.mark.asyncio
    async def test_uncorrelated_execution_ignored(self) -> None:
        store = InMemoryProjectionStore()
        proj = RepoCostProjection(store)

        await proj.on_workflow_completed(
            {
                "execution_id": "exec-99",
                "workflow_id": "wf-1",
                "total_cost_usd": "10.00",
                "total_tokens": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
            }
        )

        all_costs = await proj.get_all_costs()
        assert len(all_costs) == 0


_Row = dict[str, int | str | None]


class _SnapshotRecordingConnection:
    """Answers the summary and fallback reads, recording whether a snapshot was open."""

    def __init__(self, summary_rows: list[_Row], fallback_rows: list[_Row]) -> None:
        from syn_domain.contexts.organization.slices.repo_cost import timescale_query

        self._by_query = {
            timescale_query._EXECUTION_COSTS_QUERY: summary_rows,
            timescale_query._EXECUTION_COSTS_FALLBACK_QUERY: fallback_rows,
        }
        #: Every read, and whether a read-only REPEATABLE READ snapshot was open for it.
        self.reads_in_snapshot: list[bool] = []
        self._in_snapshot = False

    def transaction(self, *, isolation: str, readonly: bool) -> _SnapshotTransaction:
        return _SnapshotTransaction(self, isolation == "repeatable_read" and readonly)

    async def execute(self, query: str, *_args: object) -> str:
        assert "plan_cache_mode" in query, query
        return "SET"

    async def fetch(self, query: str, *_args: object) -> list[_Row]:
        self.reads_in_snapshot.append(self._in_snapshot)
        return self._by_query[query]


class _SnapshotTransaction:
    def __init__(self, conn: _SnapshotRecordingConnection, snapshot: bool) -> None:
        self._conn = conn
        self._snapshot = snapshot

    async def __aenter__(self) -> None:
        self._conn._in_snapshot = self._snapshot

    async def __aexit__(self, *_exc: object) -> bool:
        self._conn._in_snapshot = False
        return False


class _OneConnectionPool:
    def __init__(self, conn: _SnapshotRecordingConnection) -> None:
        self._conn = conn

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[_SnapshotRecordingConnection]:
        yield self._conn


def _summary_row(exec_id: str) -> _Row:
    return {
        "execution_id": exec_id,
        "total_input": 10,
        "total_output": 20,
        "total_cache_creation": 0,
        "total_cache_read": 0,
        "total_cost": "0.50",
    }


def _fallback_row(exec_id: str) -> _Row:
    return {
        "execution_id": exec_id,
        "total_input": 1,
        "total_output": 2,
        "total_cache_creation": 0,
        "total_cache_read": 0,
    }


@pytest.mark.unit
class TestTimescaleRepoCostReadsOneSnapshot:
    """The summary read and its token_usage fallback share one snapshot (#2251).

    At READ COMMITTED each took its own, so a session finishing between them
    was missing from the summary read and then priced at zero from its turns.
    """

    @pytest.mark.asyncio
    async def test_calculate_for_repo_reads_summary_and_fallback_in_one_snapshot(self) -> None:
        from syn_domain.contexts.organization.slices.repo_cost.timescale_query import (
            TimescaleRepoCostQuery,
        )

        store = InMemoryProjectionStore()
        await _seed_correlation(store, "acme/api", "exec-1")
        # No summary row, so the fallback runs: two reads.
        conn = _SnapshotRecordingConnection([], [_fallback_row("exec-1")])

        cost = await TimescaleRepoCostQuery(_OneConnectionPool(conn), store).calculate_for_repo(  # type: ignore[arg-type]  # a pool double
            "acme/api"
        )

        assert conn.reads_in_snapshot == [True, True]
        assert (cost.total_input_tokens, cost.execution_count) == (1, 1)

    @pytest.mark.asyncio
    async def test_calculate_all_reads_summary_and_fallback_in_one_snapshot(self) -> None:
        from syn_domain.contexts.organization.slices.repo_cost.timescale_query import (
            TimescaleRepoCostQuery,
        )

        store = InMemoryProjectionStore()
        await _seed_correlation(store, "acme/api", "exec-1")
        await _seed_correlation(store, "acme/api", "exec-2")
        # exec-1 has a summary, exec-2 does not: the fallback runs for exec-2.
        conn = _SnapshotRecordingConnection([_summary_row("exec-1")], [_fallback_row("exec-2")])

        costs = await TimescaleRepoCostQuery(_OneConnectionPool(conn), store).calculate_all()  # type: ignore[arg-type]  # a pool double

        assert conn.reads_in_snapshot == [True, True]
        assert [(c.total_input_tokens, c.execution_count) for c in costs] == [(11, 2)]
