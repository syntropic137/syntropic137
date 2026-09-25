"""A third harness needs only the extraction port (#1398, acceptance row 14).

A fake harness with its own private transcript format implements ONLY
``NativeSessionEvidencePort``. Its fixtures run through the real capture
handler, evidence journal contract, relationship resolver, snapshot build,
publication and the HTTP inventory route, and must produce the same
normalized inventory as Claude and Codex fixtures describing the same
topology. Nothing in the resolver, API or replication path is told the fake
exists; ``ci/fitness/code_quality/test_harness_format_boundary.py`` separately
proves those modules carry no harness-name branch or vendor format.

The fake is injected at the Syntropic137 port, not through the
agentic-primitives registry: ``get_harness`` resolves only the closed
``AgentName`` enum, so an unknown harness cannot be registered there without
editing AP (AgentParadise/agentic-primitives#434).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from syn_adapters.session_inventory.native_evidence import AgenticNativeSessionEvidence
from syn_api.inventory_types import SessionInventoryPageResponse, SessionInventoryResponse
from syn_api.routes.executions import inventory as inventory_route
from syn_domain.contexts.agent_sessions import (
    CaptureLocalTranscriptHandler,
    EvidenceBatch,
    InventoryNotFound,
    LocalTranscriptCapture,
    NativeRelationshipFact,
    NativeTranscriptFacts,
    RunIdentity,
)
from syn_domain.contexts.agent_sessions._shared.inventory_reconciliation import (
    ReconciliationRequest,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    CaptureReceipt,
    InventoryCoverage,
    InventoryGap,
    InventoryNode,
    InventoryNodeRef,
    LineageEdge,
)
from syn_domain.contexts.agent_sessions.domain.services.session_relationship_resolver import (
    RESOLVER_VERSION,
)
from syn_domain.contexts.agent_sessions.ports.SessionEvidenceReadPort import (
    EvidencePage,
    StoredEvidenceBatch,
)
from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import (
    ArchivedTranscript,
)
from syn_domain.contexts.agent_sessions.slices.reconcile_session_inventory.BuildInventorySnapshotHandler import (
    BuildInventorySnapshotHandler,
)

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions import InventorySnapshot
    from syn_domain.contexts.agent_sessions.ports.NativeSessionEvidencePort import (
        NativeSessionEvidencePort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionInventoryReadPort import (
        InventoryCounts,
        InventoryItem,
        InventoryPage,
        ItemKind,
    )

pytestmark = pytest.mark.unit

THIRD = "third-harness"
_KINDS: tuple[ItemKind, ...] = ("node", "membership", "edge", "capture", "gap", "binding")


# ---------------------------------------------------------------------------
# The fake harness: a private line format and ONE port implementation.
# ---------------------------------------------------------------------------


class FakeThirdHarnessEvidence:
    """Implements NativeSessionEvidencePort for a format nobody else knows.

    Format (one directive per line): ``self <id>``, ``root <id>``,
    ``spawned <child> call <call-id>`` (parent-side call result) and
    ``parent <id>`` (child-side header).
    """

    VERSION = "third-harness-evidence/1"

    def extract(self, harness: str, content: bytes) -> NativeTranscriptFacts:
        if harness != THIRD:
            return NativeTranscriptFacts(
                native_id=None,
                supported=False,
                issues=("unsupported_harness_evidence",),
                extractor_version=self.VERSION,
                byte_count=len(content),
            )
        native_id: str | None = None
        root_id: str | None = None
        identity: list[int] = []
        relationships: list[NativeRelationshipFact] = []
        for lineno, line in enumerate(content.decode().splitlines(), 1):
            words = line.split()
            if words[:1] == ["self"]:
                native_id = words[1]
                identity.append(lineno)
            elif words[:1] == ["root"]:
                root_id = words[1]
            elif words[:1] == ["spawned"] and native_id is not None:
                relationships.append(
                    NativeRelationshipFact(
                        parent_native_id=native_id,
                        child_native_id=words[1],
                        relation="spawn",
                        basis="parent_call_result",
                        mechanism="third-harness-spawn",
                        source_lines=(lineno,),
                        call_id=words[3],
                    )
                )
            elif words[:1] == ["parent"] and native_id is not None:
                relationships.append(
                    NativeRelationshipFact(
                        parent_native_id=words[1],
                        child_native_id=native_id,
                        relation="spawn",
                        basis="child_header",
                        mechanism="third-harness-header",
                        source_lines=(lineno,),
                    )
                )
        return NativeTranscriptFacts(
            native_id=native_id,
            root_native_id=root_id,
            identity_lines=tuple(identity),
            relationships=tuple(relationships),
            extractor_version=self.VERSION,
            byte_count=len(content),
        )

    def extract_envelope(self, harness: str, content: bytes) -> NativeTranscriptFacts:
        return NativeTranscriptFacts(
            native_id=None,
            supported=False,
            issues=("unsupported_envelope_evidence",),
            extractor_version=self.VERSION,
            byte_count=len(content),
        )


# ---------------------------------------------------------------------------
# Port-contract doubles for storage. Behaviour mirrors the Postgres adapters
# (bounded pages, publish-before-read, head fencing); no harness knowledge.
# ---------------------------------------------------------------------------


@dataclass
class ContractArchive:
    bodies: dict[str, bytes] = field(default_factory=dict)

    async def put(self, body: bytes) -> ArchivedTranscript:
        digest = hashlib.sha256(body).hexdigest()
        self.bodies[digest] = body
        return ArchivedTranscript(sha256=digest, size=len(body))

    async def get(self, reference: ArchivedTranscript) -> bytes | None:
        return self.bodies.get(reference.sha256)

    async def is_deleted(self, reference: ArchivedTranscript) -> bool:
        return False


@dataclass
class ContractJournal:
    batches: list[StoredEvidenceBatch] = field(default_factory=list)

    async def append(self, batch: EvidenceBatch) -> int:
        for stored in self.batches:
            if stored.batch.batch_id == batch.batch_id:
                return stored.sequence
        self.batches.append(StoredEvidenceBatch(sequence=len(self.batches) + 1, batch=batch))
        return len(self.batches)

    async def watermark(self, run: RunIdentity) -> int:
        return len(self.batches)

    async def read(
        self, run: RunIdentity, watermark: int, *, after: int = 0, limit: int = 100
    ) -> EvidencePage:
        eligible = [b for b in self.batches if after < b.sequence <= watermark]
        visible = eligible[:limit]
        more = len(eligible) > limit
        return EvidencePage(
            watermark=watermark,
            items=tuple(visible),
            next_after=visible[-1].sequence if more else None,
        )


@dataclass
class ContractInventory:
    snapshots: dict[UUID, InventorySnapshot] = field(default_factory=dict)
    items: dict[tuple[UUID, str], list[InventoryItem]] = field(default_factory=dict)
    published: set[UUID] = field(default_factory=set)
    heads: dict[RunIdentity, UUID] = field(default_factory=dict)

    async def stage(self, snapshot: InventorySnapshot) -> None:
        self.snapshots[snapshot.snapshot_id] = snapshot

    async def append(
        self,
        run: RunIdentity,
        snapshot_id: UUID,
        kind: ItemKind,
        start: int,
        items: tuple[InventoryItem, ...],
    ) -> None:
        bucket = self.items.setdefault((snapshot_id, kind), [])
        assert len(bucket) == start, "batches must append contiguously"
        bucket.extend(items)

    async def publish(
        self, run: RunIdentity, snapshot_id: UUID, expected_head: UUID | None
    ) -> None:
        assert self.heads.get(run) == expected_head, "stale head"
        self.published.add(snapshot_id)
        self.heads[run] = snapshot_id

    async def head(self, run: RunIdentity) -> InventorySnapshot | None:
        head = self.heads.get(run)
        return self.snapshots[head] if head is not None else None

    async def page(
        self,
        run: RunIdentity,
        snapshot_id: UUID,
        kind: ItemKind,
        *,
        after: int = -1,
        limit: int = 100,
    ) -> InventoryPage:
        from syn_domain.contexts.agent_sessions import InventoryPage

        if snapshot_id not in self.published:
            raise InventoryNotFound("no published snapshot in this run")
        bucket = self.items.get((snapshot_id, kind), [])
        visible = bucket[after + 1 : after + 1 + limit]
        last = after + len(visible)
        return InventoryPage(
            snapshot=self.snapshots[snapshot_id],
            kind=kind,
            items=tuple(visible),
            next_after=last if last + 1 < len(bucket) else None,
        )


@dataclass
class _Jobs:
    async def latest(self, run: RunIdentity) -> None:
        return None


@dataclass
class _Bodies:
    async def overrides(self, page: InventoryPage) -> tuple[()]:
        return ()


@dataclass
class _Runtime:
    inventory: ContractInventory
    evidence: ContractJournal
    jobs: _Jobs = field(default_factory=_Jobs)
    body_availability: _Bodies = field(default_factory=_Bodies)


# ---------------------------------------------------------------------------
# Harness-neutral pipeline: identical code for every harness.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fixture:
    harness: str
    extractor: NativeSessionEvidencePort
    transcripts: tuple[bytes, ...]
    roles: dict[str, str]  # native id -> role


@dataclass(frozen=True)
class Normalized:
    """The API's answer with harness identity replaced by roles and provenance dropped."""

    status: str
    later: bool
    counts: InventoryCounts
    coverage: InventoryCoverage
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str, str, str], ...]
    captures: tuple[tuple[str, str], ...]
    gaps: tuple[tuple[str, tuple[str, ...]], ...]
    memberships: int
    bindings: int


async def _pipeline(fixture: Fixture, monkeypatch: pytest.MonkeyPatch) -> Normalized:
    run = RunIdentity(source_instance_id="installation", execution_id=f"run-{fixture.harness}")
    archive, journal, store = ContractArchive(), ContractJournal(), ContractInventory()
    capture = CaptureLocalTranscriptHandler(archive, journal, fixture.extractor)
    for index, body in enumerate(fixture.transcripts):
        result = await capture.handle(
            LocalTranscriptCapture(
                run=run,
                capture_id=f"capture-{index}",
                harness=fixture.harness,
                receipt_sequence=1,
                content=body,
            )
        )
        assert result.native_id is not None, result.issues
    request = ReconciliationRequest(
        run=run,
        evidence_watermark=await journal.watermark(run),
        expected_head=None,
        snapshot_id=uuid4(),
        resolver_version=RESOLVER_VERSION,
    )
    snapshot = await BuildInventorySnapshotHandler(
        journal, store, max_evidence_records=1000, max_evidence_batches=100
    ).handle(request)
    await store.publish(run, snapshot.snapshot_id, None)

    runtime = _Runtime(inventory=store, evidence=journal)

    async def visible(_execution_id: str) -> RunIdentity:
        return run

    monkeypatch.setattr(inventory_route, "_visible_run", visible)
    monkeypatch.setattr(inventory_route, "get_inventory_runtime", lambda: runtime)
    app = FastAPI()
    app.include_router(inventory_route.router)
    client = TestClient(app)
    base = f"/executions/{run.execution_id}/session-inventory"
    response = client.get(base)
    assert response.status_code == 200
    head = SessionInventoryResponse.model_validate(response.json())
    pages: dict[ItemKind, list[InventoryItem]] = {}
    for kind in _KINDS:
        items: list[InventoryItem] = []
        cursor = -1
        while True:  # limit=1 walks every cursor: bounded paging is harness-neutral too
            response = client.get(f"{base}/{snapshot.snapshot_id}/{kind}?limit=1&after={cursor}")
            assert response.status_code == 200
            page = SessionInventoryPageResponse.model_validate(response.json())
            items.extend(page.items)
            if page.next_after is None:
                break
            cursor = page.next_after
        pages[kind] = items
    return _normalize(fixture, run, head, pages)


def _normalize(
    fixture: Fixture,
    run: RunIdentity,
    head: SessionInventoryResponse,
    pages: dict[ItemKind, list[InventoryItem]],
) -> Normalized:
    keys = {
        InventoryNodeRef(
            kind="transcript",
            source_instance_id=run.source_instance_id,
            harness=fixture.harness,
            local_id=native,
        ).key: role
        for native, role in fixture.roles.items()
    }

    def role(ref: InventoryNodeRef) -> str:
        assert ref.kind == "transcript" and ref.harness == fixture.harness
        return fixture.roles[ref.local_id]

    def only[T](kind: ItemKind, cls: type[T]) -> list[T]:
        typed = [item for item in pages[kind] if isinstance(item, cls)]
        assert len(typed) == len(pages[kind]), f"{kind} page returned foreign items"
        return typed

    assert head.snapshot is not None
    return Normalized(
        status=head.reconstruction_status,
        later=head.later_evidence_pending,
        counts=head.snapshot.counts,
        coverage=head.snapshot.coverage,
        nodes=tuple(sorted(role(i.ref) for i in only("node", InventoryNode))),
        edges=tuple(
            sorted(
                (role(i.parent), role(i.child), i.relation, i.confidence.value)
                for i in only("edge", LineageEdge)
            )
        ),
        captures=tuple(
            sorted((role(i.node), i.availability.value) for i in only("capture", CaptureReceipt))
        ),
        gaps=tuple(
            sorted(
                (i.reason, tuple(sorted(keys[k] for k in i.node_keys)))
                for i in only("gap", InventoryGap)
            )
        ),
        memberships=len(pages["membership"]),
        bindings=len(pages["binding"]),
    )


# ---------------------------------------------------------------------------
# Fixtures describing the same topology in three formats.
# ---------------------------------------------------------------------------


def _jsonl(*rows: object) -> bytes:
    return ("\n".join(json.dumps(row) for row in rows) + "\n").encode()


def _claude_parent(child: str) -> bytes:
    return _jsonl(
        {
            "sessionId": "root",
            "message": {"content": [{"type": "tool_use", "name": "Agent", "id": "call"}]},
        },
        {
            "sessionId": "root",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "call"}]},
            "toolUseResult": {"agentId": child},
        },
    )


_CLAUDE_CHILD = _jsonl({"sessionId": "root", "agentId": "b", "isSidechain": True})
_CODEX_ROOT = _jsonl({"type": "session_meta", "payload": {"id": "root", "session_id": "root"}})
_CODEX_CHILD = _jsonl(
    {
        "type": "session_meta",
        "payload": {
            "id": "child",
            "session_id": "root",
            "multi_agent_version": "v2",
            "parent_thread_id": "root",
            "source": {"subagent": {"thread_spawn": {"parent_thread_id": "root", "depth": 1}}},
        },
    }
)
_FAKE = FakeThirdHarnessEvidence()
_FAKE_LEAD_CALLS = b"self lead-7\nroot lead-7\nspawned helper-9 call c1\n"
_FAKE_HELPER = b"self helper-9\nroot lead-7\n"
_FAKE_LEAD = b"self lead-7\nroot lead-7\n"
_FAKE_HELPER_HEADER = b"self helper-9\nroot lead-7\nparent lead-7\n"
_AP = AgenticNativeSessionEvidence()
_CLAUDE_ROLES = {"root": "leader", "agent-b": "child"}
_CODEX_ROLES = {"root": "leader", "child": "child"}
_FAKE_ROLES = {"lead-7": "leader", "helper-9": "child"}

#: (name, real-harness fixture, fake fixture). Each pair is the same topology.
_EQUIVALENCES = {
    "parent-call-result, child captured": (
        Fixture("claude", _AP, (_claude_parent("b"), _CLAUDE_CHILD), _CLAUDE_ROLES),
        Fixture(THIRD, _FAKE, (_FAKE_LEAD_CALLS, _FAKE_HELPER), _FAKE_ROLES),
    ),
    "parent-call-result, child missing": (
        Fixture("claude", _AP, (_claude_parent("b"),), _CLAUDE_ROLES),
        Fixture(THIRD, _FAKE, (_FAKE_LEAD_CALLS,), _FAKE_ROLES),
    ),
    "child-header, both captured": (
        Fixture("codex", _AP, (_CODEX_ROOT, _CODEX_CHILD), _CODEX_ROLES),
        Fixture(THIRD, _FAKE, (_FAKE_LEAD, _FAKE_HELPER_HEADER), _FAKE_ROLES),
    ),
    "child-header, parent missing": (
        Fixture("codex", _AP, (_CODEX_CHILD,), _CODEX_ROLES),
        Fixture(THIRD, _FAKE, (_FAKE_HELPER_HEADER,), _FAKE_ROLES),
    ),
}


@pytest.mark.parametrize("case", sorted(_EQUIVALENCES))
async def test_third_harness_matches_real_harness_through_api(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real, fake = _EQUIVALENCES[case]
    expected = await _pipeline(real, monkeypatch)
    actual = await _pipeline(fake, monkeypatch)
    assert actual == expected
    # Guard against a vacuous equality: the topology must actually be present.
    assert expected.status == "current"
    assert expected.edges, expected


async def test_fixture_outcomes_are_the_intended_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin what each topology means, so equality above cannot hide a shared regression."""
    both = await _pipeline(_EQUIVALENCES["parent-call-result, child captured"][1], monkeypatch)
    assert both.nodes == ("child", "leader")
    assert ("leader", "child", "spawn", "corroborated") in both.edges
    assert both.captures == (("child", "present"), ("leader", "present"))
    missing = await _pipeline(_EQUIVALENCES["parent-call-result, child missing"][1], monkeypatch)
    assert {edge[3] for edge in missing.edges} == {"candidate"}
    assert ("unresolved_parentage", ("child", "leader")) in missing.gaps


def test_agentic_primitives_registry_rejects_the_third_harness() -> None:
    """Why the fake sits at the Syntropic137 port (AgentParadise/agentic-primitives#434).

    When AP can register an unknown harness, drive this fake through
    ``AgenticNativeSessionEvidence`` instead and delete this pin.
    """
    facts = AgenticNativeSessionEvidence().extract(THIRD, _FAKE_HELPER)
    assert facts.supported is False
    assert facts.issues == ("unsupported_harness_evidence",)
