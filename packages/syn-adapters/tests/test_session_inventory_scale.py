"""Row 8 (#1398): scale, concurrent revisions, filtered keyset pages, and indexed SQL.

Real Postgres only. Over 500 evidence batches reconstruct over 1,000 nodes; a
concurrent writer publishes newer revisions while a reader traverses the pinned
one. Every traversal must be loss-free and duplicate-free, and every edge
endpoint on another page must resolve through the node-by-key lookup.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.postgres_inventory import PostgresSessionInventory
from syn_adapters.session_inventory.postgres_queries import page_sql
from syn_domain.contexts.agent_sessions import (
    EvidenceBatch,
    InventoryFilter,
    InventoryItem,
    InventoryItemKeys,
    InventoryNode,
    InventoryNotFound,
    InventorySnapshot,
    ItemKind,
    LineageEdge,
    Membership,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    LineageEvidence,
    MembershipEvidence,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    EvidenceClass,
    EvidenceReference,
    InventoryNodeRef,
)
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    RESOLVER_VERSION,
)
from syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.BuildInventorySnapshotHandler import (
    BuildInventorySnapshotHandler,
)

if TYPE_CHECKING:
    import asyncpg

pytestmark = pytest.mark.integration

NODES = 1102
BATCHES = NODES // 2  # 551 historical observations
PAGE = 37  # Deliberately not a divisor of any section size.
PHASES = ("phase-a", "phase-b", "phase-c")
ATTEMPTS = ("attempt-1", "attempt-2")


def _ref(run: RunIdentity, index: int) -> InventoryNodeRef:
    return InventoryNodeRef(
        kind="transcript",
        source_instance_id=run.source_instance_id,
        harness="third-harness",
        local_id=f"native-{index}",
    )


def _evidence(name: str) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=name,
        producer_id="scale-adapter",
        source_revision="1",
        locator=name,
        extractor_version="third-harness/1",
    )


def _claims(run: RunIdentity, index: int) -> tuple[MembershipEvidence, LineageEvidence | None]:
    member = MembershipEvidence(
        node=_ref(run, index),
        run=run,
        phase_id=PHASES[index % len(PHASES)],
        attempt_id=ATTEMPTS[(index // len(PHASES)) % len(ATTEMPTS)],
        confidence=EvidenceClass.REGISTERED,
        evidence=_evidence(f"member-{index}"),
    )
    # A binary spawn tree: parents sit far earlier in node order than children,
    # so parent and child routinely land on different pages.
    edge = (
        LineageEvidence(
            parent=_ref(run, (index - 1) // 2),
            child=_ref(run, index),
            relation="spawn",
            confidence=EvidenceClass.CORROBORATED,
            evidence=_evidence(f"edge-{index}"),
        )
        if index
        else None
    )
    return member, edge


async def _observe(journal: PostgresSessionEvidence, run: RunIdentity, indexes: range) -> int:
    members: list[MembershipEvidence] = []
    edges: list[LineageEvidence] = []
    for index in indexes:
        member, edge = _claims(run, index)
        members.append(member)
        if edge is not None:
            edges.append(edge)
    return await journal.append(
        EvidenceBatch(
            batch_id=f"observation-{indexes.start}",
            producer_id="scale-adapter",
            evidence=SessionEvidence(run=run, memberships=tuple(members), edges=tuple(edges)),
        )
    )


async def _publish(
    journal: PostgresSessionEvidence,
    inventory: PostgresSessionInventory,
    run: RunIdentity,
    watermark: int,
    head: UUID | None,
) -> InventorySnapshot:
    snapshot = await BuildInventorySnapshotHandler(
        journal, inventory, max_evidence_records=100_000, max_evidence_batches=2_000
    ).handle(
        ReconciliationRequest(
            run=run,
            evidence_watermark=watermark,
            expected_head=head,
            snapshot_id=uuid4(),
            resolver_version=RESOLVER_VERSION,
        )
    )
    await inventory.publish(run, snapshot.snapshot_id, head)
    return snapshot


async def _traverse(
    inventory: PostgresSessionInventory,
    run: RunIdentity,
    snapshot_id: UUID,
    kind: ItemKind,
    filters: InventoryFilter,
    on_page: asyncio.Event | None = None,
    midway: asyncio.Event | None = None,
) -> tuple[list[InventoryItem], list[InventoryItemKeys], list[int]]:
    items: list[InventoryItem] = []
    keys: list[InventoryItemKeys] = []
    page_of: list[int] = []
    after = -1
    number = 0
    while True:
        page = await inventory.query(
            run, snapshot_id, kind, filters=filters, after=after, limit=PAGE
        )
        assert page.snapshot.snapshot_id == snapshot_id
        items.extend(page.items)
        keys.extend(page.item_keys)
        page_of.extend([number] * len(page.items))
        number += 1
        if on_page is not None:
            on_page.set()
        if midway is not None and number == 2:
            # Hold the traversal open until a newer revision is committed.
            await asyncio.wait_for(midway.wait(), timeout=120)
        await asyncio.sleep(0.01)  # Let the concurrent writer interleave.
        if not page.has_more:
            return items, keys, page_of
        assert page.last_ordinal is not None and page.last_ordinal > after
        after = page.last_ordinal


@pytest.fixture
async def stores(
    db_pool: asyncpg.Pool,
) -> tuple[PostgresSessionEvidence, PostgresSessionInventory]:
    journal = PostgresSessionEvidence(db_pool)
    inventory = PostgresSessionInventory(db_pool)
    await journal.ensure_ready()
    await inventory.ensure_ready()
    return journal, inventory


async def test_large_inventory_pages_without_loss_under_concurrent_revisions(
    db_pool: asyncpg.Pool,
    stores: tuple[PostgresSessionEvidence, PostgresSessionInventory],
) -> None:
    journal, inventory = stores
    run = RunIdentity(source_instance_id=f"scale-{uuid4()}", execution_id="workflow-run")
    watermark = 0
    for start in range(0, NODES, 2):
        watermark = await _observe(journal, run, range(start, start + 2))
    assert watermark == BATCHES > 500
    pinned = await _publish(journal, inventory, run, watermark, None)
    assert pinned.counts.node == NODES > 1000
    assert pinned.counts.membership == NODES
    assert pinned.counts.edge == NODES - 1

    started = asyncio.Event()
    committed = asyncio.Event()
    reading = True
    published: list[InventorySnapshot] = []
    during_read = 0

    async def writer() -> None:
        head, mark, extra = pinned.snapshot_id, watermark, NODES
        await started.wait()
        while reading or not published:
            mark = await _observe(journal, run, range(extra, extra + 2))
            extra += 2
            newer = await _publish(journal, inventory, run, mark, head)
            published.append(newer)
            committed.set()
            head = newer.snapshot_id

    async def reader() -> dict[
        ItemKind, tuple[list[InventoryItem], list[InventoryItemKeys], list[int]]
    ]:
        nonlocal reading, during_read
        try:
            return {
                kind: await _traverse(
                    inventory, run, pinned.snapshot_id, kind, InventoryFilter(), started, committed
                )
                for kind in ("node", "membership", "edge")
            }
        finally:
            reading = False
            during_read = len(published)

    traversed, _ = await asyncio.gather(reader(), writer())
    head = await inventory.head(run)
    assert published and head is not None and head.snapshot_id == published[-1].snapshot_id
    # The writer really published newer revisions while the reader was paging.
    assert during_read >= 1
    assert head.counts.node > NODES

    # Loss- and duplicate-free: the pinned revision only, every record exactly once.
    expected_refs = {_ref(run, index) for index in range(NODES)}
    node_items, node_keys, node_pages = traversed["node"]
    node_refs = [item.ref for item in node_items if isinstance(item, InventoryNode)]
    assert len(node_refs) == len(set(node_refs)) == NODES
    assert set(node_refs) == expected_refs
    assert [k.node_key for k in node_keys] == [ref.key for ref in node_refs]
    members = [item for item in traversed["membership"][0] if isinstance(item, Membership)]
    assert len(members) == len({m.node for m in members}) == NODES
    edge_items = [item for item in traversed["edge"][0] if isinstance(item, LineageEdge)]
    assert len(edge_items) == len({(e.parent, e.child) for e in edge_items}) == NODES - 1

    # Cross-page parent edges remain navigable through the node-by-key lookup.
    page_by_key = {ref.key: page for ref, page in zip(node_refs, node_pages, strict=True)}
    edge_keys = traversed["edge"][1]
    crossing = 0
    for edge, keys in zip(edge_items, edge_keys, strict=True):
        assert keys.node_key == edge.parent.key and keys.peer_key == edge.child.key
        if page_by_key[edge.parent.key] != page_by_key[edge.child.key]:
            crossing += 1
        resolved = await inventory.node(run, pinned.snapshot_id, edge.parent.key)
        assert resolved is not None and resolved.ref == edge.parent
    assert crossing > NODES // 2
    # Later revisions do not leak into the pinned one; unknown keys stay unresolved.
    later = _ref(run, NODES).key
    assert await inventory.node(run, pinned.snapshot_id, later) is None
    assert await inventory.node(run, head.snapshot_id, later) is not None
    assert await inventory.node(run, pinned.snapshot_id, "0" * 64) is None
    foreign = run.model_copy(update={"execution_id": "another-run"})
    with pytest.raises(InventoryNotFound):
        await inventory.node(foreign, pinned.snapshot_id, node_refs[0].key)

    # Membership narrowing in SQL agrees with the reference filter over the full traversal.
    for filters in (
        InventoryFilter(phase_id="phase-b"),
        InventoryFilter(attempt_id="attempt-2"),
        InventoryFilter(phase_id="phase-c", attempt_id="attempt-1"),
        InventoryFilter(phase_id="no-such-phase"),
    ):
        selected = {
            m.node
            for m in members
            if filters.phase_id in (None, m.phase_id) and filters.attempt_id in (None, m.attempt_id)
        }
        got_members, _, _ = await _traverse(
            inventory, run, pinned.snapshot_id, "membership", filters
        )
        assert {m.node for m in got_members if isinstance(m, Membership)} == selected
        assert len(got_members) == len(selected)
        got_nodes, _, _ = await _traverse(inventory, run, pinned.snapshot_id, "node", filters)
        assert [n.ref for n in got_nodes if isinstance(n, InventoryNode)] == [
            ref for ref in node_refs if ref in selected
        ]
        got_edges, _, _ = await _traverse(inventory, run, pinned.snapshot_id, "edge", filters)
        assert [e for e in got_edges if isinstance(e, LineageEdge)] == [
            e for e in edge_items if e.parent in selected or e.child in selected
        ]


def _scans(plan: dict[str, object]) -> list[tuple[str, str]]:
    found = [(str(plan.get("Node Type")), str(plan.get("Relation Name", "")))]
    children = plan.get("Plans", [])
    assert isinstance(children, list)
    for child in children:
        assert isinstance(child, dict)
        found.extend(_scans(child))
    return found


async def test_page_queries_are_bounded_and_index_served(
    db_pool: asyncpg.Pool,
    stores: tuple[PostgresSessionEvidence, PostgresSessionInventory],
) -> None:
    journal, inventory = stores
    run = RunIdentity(source_instance_id=f"plan-{uuid4()}", execution_id="workflow-run")
    watermark = 0
    for start in range(0, NODES, 2):
        watermark = await _observe(journal, run, range(start, start + 2))
    snapshot = await _publish(journal, inventory, run, watermark, None)
    async with db_pool.acquire() as conn:
        await conn.execute("ANALYZE session_inventory_items")
        await conn.execute("ANALYZE session_evidence_batches")
        statements: list[tuple[str, tuple[object, ...]]] = []
        for kind in ("node", "membership", "edge", "capture", "gap", "binding", "retraction"):
            for filters in (
                InventoryFilter(),
                InventoryFilter(phase_id="phase-a"),
                InventoryFilter(attempt_id="attempt-1"),
                InventoryFilter(phase_id="phase-a", attempt_id="attempt-1"),
            ):
                sql, params = page_sql(kind, filters)
                assert "LIMIT $6" in sql
                statements.append(
                    (
                        sql,
                        (
                            run.source_instance_id,
                            run.execution_id,
                            snapshot.snapshot_id,
                            kind,
                            500,
                            PAGE + 1,
                            *params,
                        ),
                    )
                )
        statements.append(
            (
                """SELECT i.payload::text FROM session_inventory_items i
                WHERE i.source_instance_id=$1 AND i.execution_id=$2 AND i.snapshot_id=$3
                AND i.kind='node' AND i.node_key=$4 LIMIT 1""",
                (run.source_instance_id, run.execution_id, snapshot.snapshot_id, "a" * 64),
            )
        )
        statements.append(
            (
                """SELECT sequence::text,payload::text FROM session_evidence_batches
                WHERE source_instance_id=$1 AND execution_id=$2 AND sequence>$3 AND sequence<=$4
                ORDER BY session_evidence_batches.sequence LIMIT $5""",
                (run.source_instance_id, run.execution_id, 100, watermark, 101),
            )
        )
        for sql, args in statements:
            raw = await conn.fetchval(f"EXPLAIN (FORMAT JSON) {sql}", *args)
            assert raw is not None
            plan = json.loads(raw)[0]["Plan"]
            scans = _scans(plan)
            big = [
                node
                for node, relation in scans
                if relation in ("session_inventory_items", "session_evidence_batches")
            ]
            assert big, sql
            assert all(node != "Seq Scan" for node in big), (sql, scans)
            assert plan["Node Type"] == "Limit", sql


async def test_rows_written_before_query_columns_are_backfilled(
    db_pool: asyncpg.Pool,
    stores: tuple[PostgresSessionEvidence, PostgresSessionInventory],
) -> None:
    journal, inventory = stores
    run = RunIdentity(source_instance_id=f"legacy-{uuid4()}", execution_id="workflow-run")
    watermark = 0
    for start in range(0, 10, 2):
        watermark = await _observe(journal, run, range(start, start + 2))
    snapshot = await _publish(journal, inventory, run, watermark, None)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """UPDATE session_inventory_items SET node_key=NULL,peer_key=NULL,phase_key=NULL,
            attempt_key=NULL,keys_indexed=FALSE WHERE source_instance_id=$1""",
            run.source_instance_id,
        )
    filters = InventoryFilter(phase_id="phase-a")
    assert not (
        await inventory.query(run, snapshot.snapshot_id, "membership", filters=filters)
    ).items
    await PostgresSessionInventory(db_pool).ensure_ready()
    page = await inventory.query(run, snapshot.snapshot_id, "membership", filters=filters)
    assert {m.node.local_id for m in page.items if isinstance(m, Membership)} == {
        f"native-{i}" for i in range(10) if i % 3 == 0
    }
    assert await inventory.node(run, snapshot.snapshot_id, _ref(run, 3).key) is not None
