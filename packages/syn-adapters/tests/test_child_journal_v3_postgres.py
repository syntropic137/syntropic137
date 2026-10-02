"""Schema v3 child journal through real Postgres evidence, resolver and inventory (#1398).

The AW typed reader parses the producer's exact export; the drain persists it
in the central journal; a restarted reader rebuilds the snapshot. Each v3 field
must survive persistence as the same typed outcome, ``pending`` must block the
seal until the deadline and then become a gap, and v2 pages keep working.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from agentic_isolation.child_journal import WorkspaceChildJournalReader
from agentic_isolation.providers.base import ExecuteResult

from syn_adapters.session_inventory.child_journal import ChildJournalDrain
from syn_adapters.session_inventory.evidence_reader import PostgresSessionEvidence
from syn_adapters.session_inventory.postgres_inventory import PostgresSessionInventory
from syn_domain.contexts.agent_sessions import EvidenceBatch, RunIdentity
from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_evidence import (
    CoverageContract,
    MembershipEvidence,
    RunSettlementEvidence,
    RunSettlementStage,
    SessionEvidence,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    CoverageState,
    EvidenceClass,
    EvidenceReference,
    IdentityBinding,
    InventoryGap,
    InventoryNodeRef,
)
from syn_domain.contexts.agent_sessions.domain.services.gap_reasons import GapReason
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    RESOLVER_VERSION,
)
from syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.BuildInventorySnapshotHandler import (
    BuildInventorySnapshotHandler,
)

if TYPE_CHECKING:
    import asyncpg

    from syn_domain.contexts.agent_sessions import InventorySnapshot

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parent / "fixtures" / "child_journal"


def reference(name: str) -> EvidenceReference:
    return EvidenceReference(
        producer_id="host",
        evidence_id=name,
        source_revision="1",
        locator=name,
        extractor_version="1",
    )


def reader(fixture: str) -> WorkspaceChildJournalReader:
    stdout = (FIXTURES / fixture).read_text()

    async def execute(command: str, **_: object) -> ExecuteResult:
        return ExecuteResult(exit_code=0, stdout=stdout, stderr="", duration_ms=0)

    return WorkspaceChildJournalReader(execute, "/spool/.agentic-session-store/p/children.sqlite")


def root(run: RunIdentity) -> InventoryNodeRef:
    return InventoryNodeRef(
        kind="invocation", source_instance_id=run.source_instance_id, local_id="root-invocation"
    )


async def host(journal: PostgresSessionEvidence, run: RunIdentity) -> None:
    await journal.append(
        EvidenceBatch(
            batch_id="host",
            producer_id="host",
            evidence=SessionEvidence(
                run=run,
                memberships=(
                    MembershipEvidence(
                        node=root(run),
                        run=run,
                        phase_id="phase",
                        attempt_id="attempt-1",
                        confidence=EvidenceClass.REGISTERED,
                        evidence=reference("registered"),
                    ),
                ),
                coverage_contract=CoverageContract(
                    contract_id="syntropic-invocations/1",
                    expected_nodes=(root(run),),
                    sealed=False,
                ),
            ),
        )
    )


async def settle(
    journal: PostgresSessionEvidence, run: RunIdentity, *stages: RunSettlementStage
) -> None:
    await journal.append(
        EvidenceBatch(
            batch_id="settlement-" + "-".join(stages),
            producer_id="settlement",
            evidence=SessionEvidence(
                run=run,
                run_settlement=tuple(
                    RunSettlementEvidence(stage=stage, evidence=reference(f"settle-{stage}"))
                    for stage in stages
                ),
            ),
        )
    )


async def rebuild(
    db_pool: asyncpg.Pool, run: RunIdentity, head: UUID | None
) -> tuple[InventorySnapshot, dict[str, set[str]], list[IdentityBinding]]:
    """A restarted reader: everything below comes from durable rows only."""
    journal = PostgresSessionEvidence(db_pool)
    inventory = PostgresSessionInventory(db_pool)
    snapshot = await BuildInventorySnapshotHandler(
        journal, inventory, max_evidence_records=1000, max_evidence_batches=100
    ).handle(
        ReconciliationRequest(
            run=run,
            evidence_watermark=await journal.watermark(run),
            expected_head=head,
            snapshot_id=uuid4(),
            resolver_version=RESOLVER_VERSION,
        )
    )
    await inventory.publish(run, snapshot.snapshot_id, head)
    gaps: dict[str, set[str]] = {}
    for item in (await inventory.page(run, snapshot.snapshot_id, "gap", limit=500)).items:
        assert isinstance(item, InventoryGap)
        for key in item.node_keys:
            gaps.setdefault(key, set()).add(item.reason)
    bindings = [
        item
        for item in (await inventory.page(run, snapshot.snapshot_id, "binding", limit=500)).items
        if isinstance(item, IdentityBinding)
    ]
    return snapshot, gaps, bindings


def child_keys(run: RunIdentity) -> dict[str, str]:
    import json

    page = json.loads((FIXTURES / "v3_native_lifecycle.json").read_text())["page"]
    return {
        change["intent"]["call"]["tool_call_id"]: InventoryNodeRef(
            kind="invocation",
            source_instance_id=run.source_instance_id,
            local_id=change["intent"]["child_invocation_id"],
        ).key
        for change in page["changes"]
    }


async def test_v3_fields_survive_postgres_and_pending_blocks_seal_until_deadline(
    db_pool: asyncpg.Pool,
) -> None:
    run = RunIdentity(source_instance_id=f"child-v3-{uuid4()}", execution_id="run")
    journal = PostgresSessionEvidence(db_pool)
    await journal.ensure_ready()
    await host(journal, run)
    drain = ChildJournalDrain(journal)
    await drain.page(
        reader("v3_native_lifecycle.json"), run=run, spool_id="spool", observation_sequence=1
    )
    watermark = await journal.watermark(run)
    # Replaying the same page is idempotent against the durable journal.
    await drain.page(
        reader("v3_native_lifecycle.json"), run=run, spool_id="spool", observation_sequence=1
    )
    assert await journal.watermark(run) == watermark
    keys = child_keys(run)

    await settle(journal, run, RunSettlementStage.EXECUTION_TERMINAL)
    terminal, gaps, bindings = await rebuild(db_pool, run, None)
    assert gaps[keys["native-pending"]] >= {GapReason.INVOCATION_PENDING}
    assert keys["native-finished"] not in gaps or not any(
        reason.startswith("invocation_") for reason in gaps[keys["native-finished"]]
    )
    for call, reason in (
        ("native-tool-failed", GapReason.LAUNCH_FAILED_NATIVE_TOOL_FAILED),
        ("native-tool-interrupted", GapReason.LAUNCH_FAILED_NATIVE_TOOL_INTERRUPTED),
        ("native-hook-watchdog", GapReason.LAUNCH_FAILED_HOOK_WATCHDOG),
        ("delegate-sandbox", GapReason.LAUNCH_FAILED_CODEX_SANDBOX_UNAVAILABLE),
        ("delegate-unreachable", GapReason.LAUNCH_FAILED_CAPTURE_HOOK_UNREACHABLE),
    ):
        assert reason in gaps[keys[call]], call
        assert GapReason.INVOCATION_LAUNCH_FAILED not in gaps[keys[call]], call
    assert GapReason.CONFLICTING_BINDING in gaps[keys["native-conflict"]]
    owned = {
        (binding.transcript.local_id, binding.confidence)
        for binding in bindings
        if binding.owner.key == keys["native-conflict"]
    }
    assert owned == {
        ("native-child-bound", EvidenceClass.CORROBORATED),
        ("native-child-rejected", EvidenceClass.CONFLICTING),
    }
    # A conflicting identity makes the run's completeness unknowable, and the
    # pending intent is never counted settled.
    assert terminal.coverage.state is CoverageState.CONFLICTING
    assert terminal.coverage.state is not CoverageState.RECONCILED

    await settle(
        journal, run, RunSettlementStage.EXECUTION_TERMINAL, RunSettlementStage.SETTLEMENT_DEADLINE
    )
    expired, gaps, _ = await rebuild(db_pool, run, terminal.snapshot_id)
    assert GapReason.INVOCATION_UNSETTLED_AT_SEAL in gaps[keys["native-pending"]]
    assert keys["native-pending"] in expired.coverage.missing_keys


async def test_pending_alone_blocks_the_seal_then_becomes_a_gap(db_pool: asyncpg.Pool) -> None:
    """Without the conflict, pending is what holds the run open, then goes missing."""
    import json

    run = RunIdentity(source_instance_id=f"child-pending-{uuid4()}", execution_id="run")
    journal = PostgresSessionEvidence(db_pool)
    await journal.ensure_ready()
    await host(journal, run)
    export = json.loads((FIXTURES / "v3_native_lifecycle.json").read_text())
    pending = [
        change
        for change in export["page"]["changes"]
        if change["intent"]["call"]["tool_call_id"] == "native-pending"
    ]
    export["page"] = {"watermark": pending[-1]["sequence"], "changes": pending, "next_after": None}
    stdout = json.dumps(export)

    async def execute(command: str, **_: object) -> ExecuteResult:
        # Bounds are the producer's; this page carries only the pending intent.
        return ExecuteResult(exit_code=0, stdout=stdout, stderr="", duration_ms=0)

    await ChildJournalDrain(journal).page(
        WorkspaceChildJournalReader(execute, "/spool/children.sqlite"),
        run=run,
        spool_id="spool",
        observation_sequence=1,
        after=pending[0]["sequence"] - 1,
    )
    key = child_keys(run)["native-pending"]
    await settle(journal, run, RunSettlementStage.EXECUTION_TERMINAL)
    terminal, gaps, _ = await rebuild(db_pool, run, None)
    assert GapReason.INVOCATION_PENDING in gaps[key]
    assert terminal.coverage.state is CoverageState.OPEN
    await settle(
        journal, run, RunSettlementStage.EXECUTION_TERMINAL, RunSettlementStage.SETTLEMENT_DEADLINE
    )
    expired, gaps, _ = await rebuild(db_pool, run, terminal.snapshot_id)
    assert GapReason.INVOCATION_UNSETTLED_AT_SEAL in gaps[key]
    assert expired.coverage.state is CoverageState.MISSING
    assert key in expired.coverage.missing_keys


async def test_v2_page_still_persists_and_settles(db_pool: asyncpg.Pool) -> None:
    run = RunIdentity(source_instance_id=f"child-v2-{uuid4()}", execution_id="run")
    journal = PostgresSessionEvidence(db_pool)
    await journal.ensure_ready()
    await ChildJournalDrain(journal).page(
        reader("v2_delegate.json"), run=run, spool_id="spool", observation_sequence=1
    )
    persisted = await journal.read(run, await journal.watermark(run))
    statuses = [
        (item.status, item.exit_code)
        for stored in persisted.items
        for item in stored.batch.evidence.invocation_lifecycle
    ]
    assert ("completed", 0) in statuses
    _, gaps, bindings = await rebuild(db_pool, run, None)
    assert not any(
        reason.startswith("invocation_") for values in gaps.values() for reason in values
    )
    assert {(b.transcript.harness, b.confidence) for b in bindings} == {
        ("codex", EvidenceClass.CORROBORATED)
    }
