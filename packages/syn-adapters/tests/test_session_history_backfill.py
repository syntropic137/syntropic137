"""Historical backfill through real PostgreSQL, archive and observability lane (#1398).

Acceptance rows 12 and 13: resumable, idempotent, billing-invariant backfill
that recovers fixture-backed historical memberships and parentage through the
live resolver, keeps unsupported and unknown evidence explicit, and produces
equivalent revisions under reordering, duplication, repetition and restarts.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest

from syn_adapters.events import AgentEventStore
from syn_adapters.session_inventory.capture_catalog import PostgresCaptureCatalog
from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.history_receipts import (
    PostgresBackfillReceipts,
    PostgresHistoryBackfillQueue,
)
from syn_adapters.session_inventory.history_source import PostgresHistoricalEvidenceSource
from syn_adapters.session_inventory.local_archive import LocalSessionTranscriptArchive
from syn_adapters.session_inventory.native_evidence import AgenticNativeSessionEvidence
from syn_adapters.session_inventory.postgres_inventory import PostgresSessionInventory
from syn_adapters.workspace_backends.agentic.capture_observation import (
    SESSION_CAPTURE_OBSERVATION,
)
from syn_domain.contexts.agent_sessions import (
    ArchivedTranscript,
    BackfillSessionInventoryHandler,
    BuildInventorySnapshotHandler,
    CataloguedCapture,
    EvidenceBatch,
    HistoryBackfillItem,
    InventoryReconciliationAggregate,
    InventorySnapshot,
    ProcessHistoryBackfillQueueHandler,
    RefreshSessionInventoryHandler,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    CoverageState,
    EvidenceClass,
    IdentityBinding,
    InventoryGap,
    InventoryNode,
    InventoryNodeRef,
    LineageEdge,
    Membership,
)
from syn_domain.contexts.agent_sessions.import_identity import platform_session_id_for
from syn_domain.contexts.agent_sessions.slices.canonical_totals.query_service import (
    CanonicalUsageQueryService,
)
from syn_domain.contexts.agent_sessions.slices.session_cost.cost_calculator import CostCalculator
from syn_domain.contexts.orchestration.slices.execution_cost.timescale_query import (
    TimescaleExecutionCostQuery,
)
from syn_shared.events import TOKEN_USAGE

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    import asyncpg

    from syn_adapters.session_inventory.database import Pool
    from syn_adapters.session_inventory.history_source import ObservationRow

pytestmark = pytest.mark.integration

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "historical_session_run_1398.json").read_text()
)
#: Pinned, not recomputed: the delegate namespace must never move (#895).
NodeTriple = tuple[str, str | None, str]
CODEX_DELEGATE_PLATFORM_ID = "07c09644-a043-5797-9903-55d38cf39d0c"


class _Repository:
    """Test double for the event-sourced management repository."""

    def __init__(self) -> None:
        self.items: dict[str, InventoryReconciliationAggregate] = {}

    async def get_by_id(self, aggregate_id: str) -> InventoryReconciliationAggregate | None:
        return self.items.get(aggregate_id)

    async def save(self, aggregate: InventoryReconciliationAggregate) -> None:
        self.items[str(aggregate.id)] = aggregate

    async def save_new(self, aggregate: InventoryReconciliationAggregate) -> None:
        if str(aggregate.id) in self.items:
            raise ValueError("stream exists")
        self.items[str(aggregate.id)] = aggregate

    async def exists(self, aggregate_id: str) -> bool:
        return aggregate_id in self.items


class _Reordered:
    """Deliver every row twice, newest-last, to prove order and duplicates are inert."""

    def __init__(self, inner: AgentEventStore, seed: int) -> None:
        self._inner, self._seed = inner, seed

    async def query_by_execution(
        self, execution_id: str, event_type: str | None = None, limit: int = 1000
    ) -> Sequence[ObservationRow]:
        rows = list(await self._inner.query_by_execution(execution_id, event_type, limit))
        doubled = [*rows, *rows]
        random.Random(self._seed).shuffle(doubled)
        return doubled[:limit]


class _CrashingJournal:
    """Fails after N appends, like a process killed mid-backfill."""

    def __init__(self, inner: PostgresSessionEvidence, crash_after: int) -> None:
        self._inner, self._left = inner, crash_after

    async def append(self, batch: EvidenceBatch) -> int:
        if self._left == 0:
            raise ConnectionResetError("simulated crash")
        self._left -= 1
        return await self._inner.append(batch)

    async def pending(self, *, limit: int = 100) -> tuple[()]:
        raise AssertionError("backfill never drains the outbox")

    async def acknowledge_dispatch(self, item: object) -> None:
        raise AssertionError("backfill never acknowledges dispatch")

    async def requeue(self, item: object) -> None:
        raise AssertionError("backfill never requeues")


@dataclass
class Stack:
    pool: Pool
    evidence: PostgresSessionEvidence
    inventory: PostgresSessionInventory
    receipts: PostgresBackfillReceipts
    catalog: PostgresCaptureCatalog
    archive: LocalSessionTranscriptArchive
    events: AgentEventStore
    repository: _Repository

    def handler(
        self,
        *,
        observations: _Reordered | None = None,
        journal: _CrashingJournal | None = None,
    ) -> BackfillSessionInventoryHandler:
        source = PostgresHistoricalEvidenceSource(
            self.pool,
            observations or self.events,
            self.archive,
            AgenticNativeSessionEvidence(),
            max_observations=100,
            max_archives=100,
        )
        refresh = RefreshSessionInventoryHandler(self.repository, self.evidence, self.inventory)
        return BackfillSessionInventoryHandler(
            source, self.receipts, journal or self.evidence, refresh
        )

    async def publish(self, run: RunIdentity, job_id: str) -> InventorySnapshot:
        """Drive the ordinary reconciliation step exactly as the live job does."""
        aggregate = await self.repository.get_by_id(job_id)
        assert aggregate is not None
        assert aggregate.state is not None
        request = aggregate.state.request
        builder = BuildInventorySnapshotHandler(
            self.evidence, self.inventory, max_evidence_records=10_000, max_evidence_batches=500
        )
        snapshot = await builder.handle(request)
        await self.inventory.publish(run, request.snapshot_id, request.expected_head)
        return snapshot


@pytest.fixture
async def stack(
    db_pool: asyncpg.Pool, test_infrastructure: object, tmp_path: Path
) -> AsyncIterator[Stack]:
    pool = cast("Pool", db_pool)
    evidence = PostgresSessionEvidence(pool)
    await evidence.ensure_ready()
    receipts = PostgresBackfillReceipts(pool)
    await receipts.ensure_ready()
    archive = LocalSessionTranscriptArchive(tmp_path)
    await archive.ensure_ready()
    async with db_pool.acquire() as conn:
        from syn_adapters.import_ledger.postgres_ledger import CREATE_TABLE_SQL

        await conn.execute(CREATE_TABLE_SQL)
    events = AgentEventStore(getattr(test_infrastructure, "timescaledb_url"))  # noqa: B009
    await events.initialize()
    yield Stack(
        pool=pool,
        evidence=evidence,
        inventory=PostgresSessionInventory(pool),
        receipts=receipts,
        catalog=PostgresCaptureCatalog(pool),
        archive=archive,
        events=events,
        repository=_Repository(),
    )
    await events.close()


def _run() -> RunIdentity:
    return RunIdentity(
        source_instance_id=f"history-{uuid4()}", execution_id=f"{FIXTURE['execution_id']}-{uuid4()}"
    )


async def _seed(stack: Stack, run: RunIdentity, *, reverse: bool = False) -> None:
    """Pre-inventory history: verdicts, billed delegates, catalogued archives."""
    archives = list(FIXTURE["archives"])
    for item in reversed(archives) if reverse else archives:
        body = ("\n".join(item["lines"]) + "\n").encode()
        if item.get("expired"):
            stored = ArchivedTranscript(sha256=hashlib.sha256(body).hexdigest(), size=len(body))
        else:
            stored = await stack.archive.put(body)
        await stack.catalog.record(
            CataloguedCapture(
                run=run,
                producer_id="pre-inventory-capture",
                capture_id=f"{run.execution_id}:{item['capture_id']}",
                harness=item["harness"],
                native_id=item.get("catalogued_native_id"),
                content_format=item["content_format"],
                archive=stored,
            )
        )
    async with stack.pool.acquire() as conn:
        for native in FIXTURE["delegate_ledger"]:
            await conn.execute(
                """INSERT INTO delegate_import_ledger
                (execution_id,harness_session_id,uncached_input_tokens,output_tokens)
                VALUES ($1,$2,800,90)""",
                run.execution_id,
                native,
            )
    rows = list(FIXTURE["capture_observations"])
    for row in reversed(rows) if reverse else rows:
        await stack.events.record_observation(
            session_id=row["session_id"],
            observation_type=SESSION_CAPTURE_OBSERVATION,
            data=dict(row["data"]),
            execution_id=run.execution_id,
            phase_id=row["phase_id"],
        )
    for usage in FIXTURE["token_usage"]:
        session = usage.get("session_id") or platform_session_id_for(usage["delegate"])
        await stack.events.record_observation(
            session_id=session,
            observation_type=TOKEN_USAGE,
            data={
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
                "model": usage["model"],
            },
            execution_id=run.execution_id,
            phase_id="plan",
        )


async def _items(
    stack: Stack, run: RunIdentity, snapshot: InventorySnapshot, kind: str
) -> list[object]:
    items: list[object] = []
    after = -1
    while True:
        page = await stack.inventory.page(run, snapshot.snapshot_id, kind, after=after, limit=500)  # type: ignore[arg-type]
        items.extend(page.items)
        if page.next_after is None:
            return items
        after = page.next_after


def _ref(node: InventoryNodeRef) -> NodeTriple:
    return (node.kind, node.harness, node.local_id)


@dataclass(frozen=True)
class SemanticView:
    nodes: list[NodeTriple]
    memberships: list[tuple[NodeTriple, str | None, str | None, str]]
    edges: list[tuple[NodeTriple, NodeTriple, str, str]]
    bindings: list[tuple[NodeTriple, NodeTriple, str]]
    gaps: list[tuple[str, tuple[NodeTriple, ...]]]
    coverage: str


async def _view(stack: Stack, run: RunIdentity, snapshot: InventorySnapshot) -> SemanticView:
    """Source-independent semantics: ignores run namespace and evidence identities."""
    nodes = [cast("InventoryNode", item) for item in await _items(stack, run, snapshot, "node")]
    by_key = {item.ref.key: _ref(item.ref) for item in nodes}
    memberships = [cast("Membership", i) for i in await _items(stack, run, snapshot, "membership")]
    edges = [cast("LineageEdge", i) for i in await _items(stack, run, snapshot, "edge")]
    bindings = [cast("IdentityBinding", i) for i in await _items(stack, run, snapshot, "binding")]
    gaps = [cast("InventoryGap", i) for i in await _items(stack, run, snapshot, "gap")]
    return SemanticView(
        nodes=sorted(by_key.values(), key=repr),
        memberships=sorted(
            {(_ref(m.node), m.phase_id, m.attempt_id, m.confidence.value) for m in memberships},
            key=repr,
        ),
        edges=sorted(
            {(_ref(e.parent), _ref(e.child), e.relation, e.confidence.value) for e in edges},
            key=repr,
        ),
        bindings=sorted(
            {(_ref(b.owner), _ref(b.transcript), b.confidence.value) for b in bindings}, key=repr
        ),
        gaps=sorted(
            {
                (g.reason, tuple(sorted(by_key.get(k, ("?", None, k)) for k in g.node_keys)))
                for g in gaps
            },
            key=repr,
        ),
        coverage=snapshot.coverage.state.value,
    )


async def _billing(stack: Stack, run: RunIdentity) -> tuple[object, ...]:
    assert stack.events.pool is not None
    cost = await TimescaleExecutionCostQuery(stack.events.pool).calculate(run.execution_id)
    totals = await CanonicalUsageQueryService(stack.events.pool, CostCalculator()).totals(
        {run.execution_id}
    )
    async with stack.events.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT time,event_type,session_id,phase_id,data::text FROM agent_events
            WHERE execution_id=$1 ORDER BY time,event_type,session_id,data::text""",
            run.execution_id,
        )
    async with stack.pool.acquire() as conn:
        ledger = await conn.fetch(
            """SELECT harness_session_id,uncached_input_tokens::text,output_tokens::text,
            updated_at::text FROM delegate_import_ledger WHERE execution_id=$1
            ORDER BY harness_session_id""",
            run.execution_id,
        )
    return (
        cost,
        totals,
        [tuple(row) for row in rows],
        [tuple(row) for row in ledger],
    )


async def _backfill_and_publish(
    stack: Stack, run: RunIdentity, key: str = "history-1", **kwargs: _Reordered
) -> tuple[InventorySnapshot, SemanticView]:
    result = await stack.handler(**kwargs).handle(run, key)
    snapshot = await stack.publish(run, result.job_id)
    return snapshot, await _view(stack, run, snapshot)


def _transcript(harness: str, native: str) -> NodeTriple:
    return ("transcript", harness, native)


def _platform(local_id: str) -> NodeTriple:
    return ("platform", None, local_id)


async def test_fixture_history_recovers_membership_and_parentage_without_inventing_completeness(
    stack: Stack,
) -> None:
    run = _run()
    await _seed(stack, run)
    snapshot, view = await _backfill_and_publish(stack, run)

    root, child = _transcript("claude", "root-a"), _transcript("claude", "agent-b")
    codex = _transcript("codex", "codex-delegate-1")
    delegate = _platform(platform_session_id_for("codex-delegate-1"))
    unknown_delegate = _platform(platform_session_id_for("unknown-delegate-9"))
    assert delegate[2] == CODEX_DELEGATE_PLATFORM_ID
    # Parentage recovered centrally from archived structured call/result evidence.
    assert view.edges == [(root, child, "spawn", EvidenceClass.CORROBORATED.value)]
    memberships = view.memberships
    # Capture sweeps are candidates, never registered phase membership.
    assert (child, "plan", None, "candidate") in memberships
    assert (root, "plan", None, "candidate") in memberships
    assert (_platform("phase-build-session"), "build", None, "candidate") in memberships
    # A verified billed alias derives run membership for its transcript.
    assert (delegate, None, None, "corroborated") in memberships
    assert (codex, None, None, "corroborated") in memberships
    assert view.bindings == [(delegate, codex, "corroborated")]
    nodes = view.nodes
    assert _transcript("claude", "lost-c") in nodes
    assert unknown_delegate in nodes
    assert all(node[2] != "orphan-z" for node in nodes), "no harness is guessed"
    gaps = {reason for reason, _ in view.gaps}
    assert {
        "legacy_capture_unsupported",
        "legacy_native_identity_unqualified",
        "legacy_archive_body_missing",
        "unsupported_harness_evidence",
    } <= gaps
    # Old unsupported observations stay unknown; legacy data never seals coverage.
    assert snapshot.coverage.state is CoverageState.UNKNOWN
    assert view.coverage == "unknown"


async def test_repeated_backfill_reuses_receipts_and_publishes_the_same_revision(
    stack: Stack,
) -> None:
    run = _run()
    await _seed(stack, run)
    first = await stack.handler().handle(run, "history-1")
    snapshot = await stack.publish(run, first.job_id)
    assert first.materialized == first.receipts > 0

    again = await stack.handler().handle(run, "history-1")
    assert again.job_id == first.job_id
    assert (again.materialized, again.receipts) == (0, first.receipts)

    other = await stack.handler().handle(run, "history-2")
    assert other.materialized == 0
    assert other.evidence_watermark == first.evidence_watermark
    rebuilt = await stack.publish(run, other.job_id)
    assert rebuilt.revision == snapshot.revision
    assert await stack.evidence.watermark(run) == first.evidence_watermark


async def test_reordered_and_duplicated_history_is_semantically_equivalent(
    stack: Stack,
) -> None:
    control = _run()
    await _seed(stack, control)
    _, expected = await _backfill_and_publish(stack, control)
    for seed in (1, 2):
        run = _run()
        await _seed(stack, run, reverse=True)
        _, view = await _backfill_and_publish(
            stack, run, observations=_Reordered(stack.events, seed)
        )
        assert view == expected


async def test_crash_mid_backfill_then_resume_matches_an_uninterrupted_run(
    stack: Stack,
) -> None:
    control = _run()
    await _seed(stack, control)
    uninterrupted = await stack.handler().handle(control, "history-1")
    _, expected = await _backfill_and_publish(stack, control)

    for crash_after in (0, 3):
        run = _run()
        await _seed(stack, run)
        with pytest.raises(ConnectionResetError):
            await stack.handler(journal=_CrashingJournal(stack.evidence, crash_after)).handle(
                run, "history-1"
            )
        receipts = await stack.receipts.existing(run)
        assert len(receipts) == uninterrupted.receipts, "materialized once, before appends"
        resumed = await stack.handler().handle(run, "history-1")
        assert resumed.materialized == 0
        assert [r.ordinal for r in await stack.receipts.existing(run)] == [
            r.ordinal for r in receipts
        ]
        # No duplicate journal batches: one per receipt.
        assert await stack.evidence.watermark(run) == uninterrupted.receipts
        snapshot = await stack.publish(run, resumed.job_id)
        assert await _view(stack, run, snapshot) == expected


async def test_backfill_never_changes_costs_session_totals_or_delegate_identity(
    stack: Stack,
) -> None:
    run = _run()
    await _seed(stack, run)
    before = await _billing(stack, run)
    assert before[0] is not None, "the fixture must carry recorded cost to protect"
    revisions = set()
    for key in ("history-1", "history-1", "history-2"):
        result = await stack.handler().handle(run, key)
        revisions.add((await stack.publish(run, result.job_id)).revision)
    assert await _billing(stack, run) == before
    assert len(revisions) == 1
    assert platform_session_id_for("codex-delegate-1") == CODEX_DELEGATE_PLATFORM_ID


async def test_bulk_queue_is_durable_idempotent_and_drained_by_the_live_worker(
    stack: Stack,
) -> None:
    source = f"history-{uuid4()}"
    runs = [
        RunIdentity(source_instance_id=source, execution_id=f"bulk-{i}-{uuid4()}") for i in range(2)
    ]
    for run in runs:
        await _seed(stack, run)
    queue = PostgresHistoryBackfillQueue(stack.pool, source)
    items = tuple(HistoryBackfillItem(run=run, idempotency_key="bulk-1") for run in runs)
    assert await queue.enqueue(items) == 2
    assert await queue.enqueue(items) == 0
    worker = ProcessHistoryBackfillQueueHandler(
        queue,
        stack.handler(),
        lease_seconds=60,
        retry_seconds=0,
        max_items_per_tick=10,
        max_attempts=2,
    )
    assert await worker.handle() == 2
    assert await worker.handle() == 0
    for run in runs:
        assert len(await stack.receipts.existing(run)) > 0
        assert await stack.evidence.watermark(run) > 0
