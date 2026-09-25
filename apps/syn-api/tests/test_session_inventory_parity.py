"""Cross-client parity golden for the session inventory (#1398 acceptance row 9).

One fixture inventory is served by the real inventory routes. Every exchange a
client could make while traversing it (status, every page of every section,
the phase-filtered pages and a cross-page node lookup) is recorded into
``fixtures/session_inventory_parity.json`` together with the digest computed
here from the API responses alone. The CLI, dashboard and OpenClaw vitest
suites replay those exchanges through their own data layers and must derive
the identical digest.

The committed fixture must equal what this test regenerates, so it cannot
drift from the API. Regenerate after an intended contract change with
``SYN_UPDATE_PARITY_FIXTURE=1 uv run pytest apps/syn-api/tests/test_session_inventory_parity.py``.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from syn_adapters.session_inventory.postgres_items import query_keys
from syn_api.routes.executions import inventory
from syn_api.types import (
    SessionInventoryNodeResponse,
    SessionInventoryPageResponse,
    SessionInventoryResponse,
)
from syn_domain.contexts.agent_sessions import (
    BodyAvailability,
    CaptureReceipt,
    CoverageState,
    EvidenceClass,
    EvidenceReference,
    EvidenceRetraction,
    IdentityBinding,
    InventoryCoverage,
    InventoryFilter,
    InventoryGap,
    InventoryNode,
    InventoryNodeRef,
    InventoryNotFound,
    InventoryQueryPage,
    InventorySnapshot,
    LineageEdge,
    Membership,
    ResolvedInventory,
    RunIdentity,
    TranscriptBodyState,
    inventory_counts,
)
from syn_domain.contexts.agent_sessions.domain.services.gap_reasons import GapReason

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import InventoryItem, ItemKind

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).parent / "fixtures" / "session_inventory_parity.json"
KINDS: tuple[ItemKind, ...] = (
    "node",
    "membership",
    "edge",
    "capture",
    "gap",
    "binding",
    "retraction",
)
PAGE_SIZE = 2
SOURCE = "installation-parity"
EXECUTION = "exec-parity-1398"
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000001398")
PHASE_FILTER = "phase-plan"
ARCHIVE = "a" * 64
REMOTE_ARCHIVE = "b" * 64

RUN = RunIdentity(source_instance_id=SOURCE, execution_id=EXECUTION)


def _ref(kind: str, local_id: str, harness: str | None = None) -> InventoryNodeRef:
    return InventoryNodeRef.model_validate(
        {"kind": kind, "source_instance_id": SOURCE, "local_id": local_id, "harness": harness}
    )


def _evidence(name: str) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"evidence-{name}",
        producer_id="producer-parity",
        source_revision="1",
        locator=f"fixture/{name}",
        extractor_version="parity/1",
    )


PLATFORM_PLAN = _ref("platform", "sess-plat-plan-0001")
PLATFORM_BUILD = _ref("platform", "sess-plat-build-0002")
INVOCATION = _ref("invocation", "inv-build-retry-0003")
CLAUDE_LEADER = _ref("transcript", "claude-native-leader-aaaa", "claude")
CLAUDE_CHILD = _ref("transcript", "claude-native-child-cccc", "claude")
CODEX_LEADER = _ref("transcript", "codex-native-leader-bbbb", "codex")


def _membership(node: InventoryNodeRef, phase: str, attempt: str) -> Membership:
    return Membership(
        node=node,
        run=RUN,
        phase_id=phase,
        attempt_id=attempt,
        confidence=EvidenceClass.REGISTERED,
        evidence=(_evidence(f"member-{node.local_id}"),),
    )


_UNAVAILABLE = tuple(sorted((INVOCATION.key, CODEX_LEADER.key)))


def _resolved() -> ResolvedInventory:
    return ResolvedInventory(
        resolver_version="parity/1",
        run=RUN,
        revision="rev-parity-1398",
        nodes=tuple(
            InventoryNode(ref=ref, evidence=(_evidence(ref.local_id),))
            for ref in (
                PLATFORM_PLAN,
                PLATFORM_BUILD,
                INVOCATION,
                CLAUDE_LEADER,
                CLAUDE_CHILD,
                CODEX_LEADER,
            )
        ),
        memberships=(
            _membership(PLATFORM_PLAN, PHASE_FILTER, "attempt-1"),
            _membership(CLAUDE_LEADER, PHASE_FILTER, "attempt-1"),
            _membership(PLATFORM_BUILD, "phase-build", "attempt-1"),
            _membership(CODEX_LEADER, "phase-build", "attempt-1"),
            _membership(INVOCATION, "phase-build", "attempt-2"),
        ),
        # The child has no membership: it is only reachable through lineage,
        # so a phase-filtered page names it by key and the node lookup resolves it.
        edges=(
            LineageEdge(
                parent=CLAUDE_LEADER,
                child=CLAUDE_CHILD,
                relation="spawn",
                confidence=EvidenceClass.CORROBORATED,
                evidence=(_evidence("edge-claude"),),
            ),
        ),
        bindings=(
            IdentityBinding(
                owner=PLATFORM_PLAN,
                transcript=CLAUDE_LEADER,
                confidence=EvidenceClass.REGISTERED,
                evidence=(_evidence("bind-plan"),),
            ),
            IdentityBinding(
                owner=PLATFORM_BUILD,
                transcript=CODEX_LEADER,
                confidence=EvidenceClass.REGISTERED,
                evidence=(_evidence("bind-build"),),
            ),
        ),
        captures=(
            CaptureReceipt(
                node=CLAUDE_LEADER,
                availability=BodyAvailability.PRESENT,
                receipt_sequence=1,
                evidence=_evidence("capture-claude-local"),
                archived_byte_hash=ARCHIVE,
            ),
            CaptureReceipt(
                node=CLAUDE_LEADER,
                availability=BodyAvailability.PRESENT,
                receipt_sequence=2,
                evidence=_evidence("capture-claude-remote"),
                destination="remote",
                archived_byte_hash=REMOTE_ARCHIVE,
            ),
            CaptureReceipt(
                node=CODEX_LEADER,
                availability=BodyAvailability.PENDING,
                receipt_sequence=3,
                evidence=_evidence("capture-codex-local"),
            ),
        ),
        # Resolver vocabulary, consistent with open coverage: the retry's
        # transport broke before its wrapper announced, and the bodies the
        # contract expects are not yet present (the resolver names them).
        gaps=(
            InventoryGap(
                reason=GapReason.INVOCATION_TRANSPORT_FAILED_BEFORE_ANNOUNCE,
                node_keys=(INVOCATION.key,),
                evidence_ids=("evidence-inv-build-retry-0003",),
            ),
            InventoryGap(reason=GapReason.EXPECTED_BODY_UNAVAILABLE, node_keys=_UNAVAILABLE),
        ),
        coverage=InventoryCoverage(
            state=CoverageState.OPEN,
            contract_id="parity-contract",
            expected_count=3,
            missing_keys=_UNAVAILABLE,
        ),
        retractions=(
            EvidenceRetraction(target=_evidence("stale"), evidence=_evidence("stale-correction")),
        ),
    )


def _sections(resolved: ResolvedInventory) -> dict[ItemKind, tuple[InventoryItem, ...]]:
    return {
        "node": resolved.nodes,
        "membership": resolved.memberships,
        "edge": resolved.edges,
        "capture": resolved.captures,
        "gap": resolved.gaps,
        "binding": resolved.bindings,
        "retraction": resolved.retractions,
    }


class _FixtureInventory:
    """Keyset reads over one published revision with the SQL filter semantics."""

    def __init__(self, resolved: ResolvedInventory) -> None:
        self.snapshot = InventorySnapshot(
            snapshot_id=SNAPSHOT_ID,
            run=RUN,
            revision=resolved.revision,
            resolver_version=resolved.resolver_version,
            evidence_watermark=7,
            coverage=resolved.coverage,
            counts=inventory_counts(resolved),
        )
        self._sections = _sections(resolved)
        self._memberships = resolved.memberships
        self._nodes = {node.ref.key: node for node in resolved.nodes}

    async def head(self, run: RunIdentity) -> InventorySnapshot | None:
        return self.snapshot if run == RUN else None

    def _member(self, key: str | None, filters: InventoryFilter) -> bool:
        return key is not None and any(
            m.node.key == key
            and (filters.phase_id is None or m.phase_id == filters.phase_id)
            and (filters.attempt_id is None or m.attempt_id == filters.attempt_id)
            for m in self._memberships
        )

    def _matches(self, kind: ItemKind, item: InventoryItem, filters: InventoryFilter) -> bool:
        if not filters.active or kind == "retraction":
            return True
        keys = query_keys(item)
        if isinstance(item, Membership):
            return (filters.phase_id is None or item.phase_id == filters.phase_id) and (
                filters.attempt_id is None or item.attempt_id == filters.attempt_id
            )
        if isinstance(item, InventoryGap):
            return not item.node_keys or any(self._member(k, filters) for k in item.node_keys)
        return self._member(keys.node_key, filters) or self._member(keys.peer_key, filters)

    async def query(
        self,
        run: RunIdentity,
        snapshot_id: UUID,
        kind: ItemKind,
        *,
        filters: InventoryFilter,
        after: int = -1,
        limit: int = 100,
    ) -> InventoryQueryPage:
        if run != RUN or snapshot_id != SNAPSHOT_ID:
            raise InventoryNotFound("unknown revision")
        rows = [
            (ordinal, item)
            for ordinal, item in enumerate(self._sections[kind])
            if ordinal > after and self._matches(kind, item, filters)
        ]
        page = rows[:limit]
        return InventoryQueryPage(
            snapshot=self.snapshot,
            kind=kind,
            filters=filters,
            items=tuple(item for _, item in page),
            item_keys=tuple(query_keys(item).item_keys for _, item in page),
            last_ordinal=page[-1][0] if page else None,
            has_more=len(rows) > limit,
        )

    async def node(
        self, run: RunIdentity, snapshot_id: UUID, node_key: str
    ) -> InventoryNode | None:
        if run != RUN or snapshot_id != SNAPSHOT_ID:
            raise InventoryNotFound("unknown revision")
        return self._nodes.get(node_key)


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _FixtureInventory]:
    store = _FixtureInventory(_resolved())
    runtime = Mock()
    runtime.inventory = store
    runtime.jobs.latest = AsyncMock(return_value=None)
    runtime.evidence.watermark = AsyncMock(return_value=store.snapshot.evidence_watermark)
    runtime.replication = None  # Remote replication disabled: local inventory still serves.
    runtime.body_availability.overrides = AsyncMock(
        return_value=(TranscriptBodyState(archive_sha256=ARCHIVE, status="expired"),)
    )
    monkeypatch.setattr(inventory, "_visible_run", AsyncMock(return_value=RUN))
    monkeypatch.setattr(inventory, "get_inventory_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(inventory.router)
    return TestClient(app), store


class _Exchange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str
    query: dict[str, str]
    status: int
    body: JsonValue


class _GapDigest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reason: str
    node_keys: list[str]


class _Digest(BaseModel):
    """What every client must derive identically from its own data path."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    revision: str
    snapshot_id: str
    coverage_state: str
    complete: bool
    counts: dict[str, int]
    traversed: dict[str, int]
    distinct_sessions: int | None
    platform_sessions: int | None
    native_transcripts: int | None
    invocations: int | None
    namespaces: dict[str, int]
    node_ids: list[str]
    gaps: list[_GapDigest]
    counts_display: str
    coverage_display: str


class _PhaseDigest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_ids: list[str]
    cross_page_child: str


class _ParityFixture(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    generated_by: str
    execution_id: str
    phase_filter: str
    exchanges: list[_Exchange]
    expected: _Digest
    expected_phase: _PhaseDigest


def _get(
    client: TestClient, exchanges: list[_Exchange], path: str, query: dict[str, str]
) -> JsonValue:
    params = {**query, "limit": str(PAGE_SIZE)} if path.split("/")[-2] != "nodes" else query
    if path.endswith("/session-inventory"):
        params = {}
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    body = TypeAdapter(JsonValue).validate_python(response.json())
    exchanges.append(_Exchange(path=path, query=query, status=200, body=body))
    return body


def _traverse(
    client: TestClient, exchanges: list[_Exchange], kind: ItemKind, filters: dict[str, str]
) -> list[InventoryItem]:
    path = f"/executions/{EXECUTION}/session-inventory/{SNAPSHOT_ID}/{kind}"
    items: list[InventoryItem] = []
    cursor: str | None = None
    while True:
        query = dict(filters)
        if cursor is not None:
            query["cursor"] = cursor
        page = SessionInventoryPageResponse.model_validate(_get(client, exchanges, path, query))
        assert page.kind == kind
        items.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            return items


def _namespace(ref: InventoryNodeRef) -> str:
    return ref.kind if ref.harness is None else f"{ref.kind}:{ref.harness}"


def _node_ids(items: list[InventoryItem]) -> list[str]:
    return sorted(
        f"{_namespace(item.ref)}/{item.ref.local_id}"
        for item in items
        if isinstance(item, InventoryNode)
    )


def _digest(
    status: SessionInventoryResponse, sections: dict[ItemKind, list[InventoryItem]]
) -> _Digest:
    """Derived only from API responses, the same way each client test derives it."""
    snapshot = status.snapshot
    assert snapshot is not None
    summary = status.summary
    namespaces: Counter[str] = Counter(
        _namespace(item.ref) for item in sections["node"] if isinstance(item, InventoryNode)
    )
    gaps = sorted(
        (
            _GapDigest(reason=gap.reason, node_keys=sorted(gap.node_keys))
            for gap in sections["gap"]
            if isinstance(gap, InventoryGap)
        ),
        key=lambda gap: (gap.reason, gap.node_keys),
    )
    return _Digest(
        revision=snapshot.revision,
        snapshot_id=str(snapshot.snapshot_id),
        coverage_state=snapshot.coverage.state.value,
        complete=summary.complete,
        counts={kind: int(getattr(snapshot.counts, kind)) for kind in KINDS},
        traversed={kind: len(sections[kind]) for kind in KINDS},
        distinct_sessions=summary.distinct_sessions,
        platform_sessions=summary.platform_sessions,
        native_transcripts=summary.native_transcripts,
        invocations=summary.invocations,
        namespaces=dict(sorted(namespaces.items())),
        node_ids=_node_ids(sections["node"]),
        gaps=gaps,
        counts_display=summary.counts_display,
        coverage_display=summary.coverage_display,
    )


def _generate(client: TestClient) -> _ParityFixture:
    exchanges: list[_Exchange] = []
    status = SessionInventoryResponse.model_validate(
        _get(client, exchanges, f"/executions/{EXECUTION}/session-inventory", {})
    )
    sections = {kind: _traverse(client, exchanges, kind, {}) for kind in KINDS}
    phase = {kind: _traverse(client, exchanges, kind, {"phase_id": PHASE_FILTER}) for kind in KINDS}
    lookup_path = (
        f"/executions/{EXECUTION}/session-inventory/{SNAPSHOT_ID}/nodes/{CLAUDE_CHILD.key}"
    )
    lookup = SessionInventoryNodeResponse.model_validate(_get(client, exchanges, lookup_path, {}))
    assert lookup.node is not None
    return _ParityFixture(
        generated_by=(
            "apps/syn-api/tests/test_session_inventory_parity.py; never hand-edit, regenerate"
        ),
        execution_id=EXECUTION,
        phase_filter=PHASE_FILTER,
        exchanges=exchanges,
        expected=_digest(status, sections),
        expected_phase=_PhaseDigest(
            node_ids=_node_ids(phase["node"]),
            cross_page_child=f"{_namespace(lookup.node.ref)}/{lookup.node.ref.local_id}",
        ),
    )


def _serialized(fixture: _ParityFixture) -> str:
    return json.dumps(fixture.model_dump(mode="json"), indent=1, sort_keys=True) + "\n"


def test_fixture_is_regenerated_from_the_api(served: tuple[TestClient, _FixtureInventory]) -> None:
    client, _ = served
    generated = _serialized(_generate(client))
    if os.environ.get("SYN_UPDATE_PARITY_FIXTURE") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(generated)
    assert FIXTURE.exists(), "run with SYN_UPDATE_PARITY_FIXTURE=1 to create the fixture"
    assert FIXTURE.read_text() == generated, (
        "parity fixture drifted from the API; regenerate with SYN_UPDATE_PARITY_FIXTURE=1"
    )


def test_fixture_exercises_every_parity_dimension(
    served: tuple[TestClient, _FixtureInventory],
) -> None:
    client, _ = served
    fixture = _generate(client)
    expected = fixture.expected
    # Multi-page sections, so a client reading only one page fails parity.
    assert expected.traversed["node"] > PAGE_SIZE
    assert expected.traversed == expected.counts
    assert expected.namespaces == {
        "invocation": 1,
        "platform": 2,
        "transcript:claude": 2,
        "transcript:codex": 1,
    }
    assert (expected.platform_sessions, expected.native_transcripts) == (2, 3)
    assert expected.complete is False  # open coverage is partial, never complete
    # The child is only reachable by lineage: absent from the phase page, resolved by lookup.
    child = f"transcript:claude/{CLAUDE_CHILD.local_id}"
    assert child not in fixture.expected_phase.node_ids
    assert fixture.expected_phase.cross_page_child == child
