"""A binary artifact survives collection, storage, the read model and the API (#990).

WHAT WAS BROKEN. `ArtifactCollector` decoded every collected file with
``decode("utf-8", errors="replace")``, and the API decoded storage again the same
way. Measured live on 2026-10-06 (PR #1648): a 32,776-byte PNG came back as
``ef bf bd 50 4e 47`` - U+FFFD then "PNG" - with 12,517 U+FFFD sequences, and
no exception anywhere.

WHY THE TEST WALKS THE WHOLE CHAIN. A value written correctly and dropped one
hop later passes every test that checks the objects at either end. So the
files go in as the bytes a workspace returns, and come out as the bytes an
HTTP client and the next phase's workspace receive:

    workspace bytes -> ArtifactCollector -> object storage + ArtifactCreated
      -> ArtifactListProjection -> GET /artifacts/{id}/raw (and the JSON detail)
      -> ArtifactQueryService -> the next phase's workspace (restart path)

The text file pins the other half of the fix: markdown must be byte-for-byte
what it was before, including its hash.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from event_sourcing.client.grpc_client import GrpcEventStoreClient
from event_sourcing.proto.eventstore.v1 import eventstore_pb2

from syn_adapters.object_storage.protocol import ObjectNotFoundError, UploadResult
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.artifact_storage.memory import InMemoryArtifactStorage
from syn_adapters.storage.artifact_storage.minio import MinioArtifactStorage
from syn_api.routes.artifacts import get_artifact, get_artifact_raw_endpoint
from syn_api.types import Ok
from syn_domain.contexts.artifacts import (
    UNREPORTED_AGENT,
    ArtifactType,
    ContentType,
    CreateArtifactCommand,
    compute_content_hash,
)
from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
    ArtifactAggregate,
)
from syn_domain.contexts.artifacts.domain.events.ArtifactCreatedEvent import (
    ArtifactCreatedEvent,
)
from syn_domain.contexts.artifacts.domain.services.artifact_query_service import (
    ArtifactQueryService,
)
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
    ArtifactListProjection,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
    UnfinishedPhase,
)
from syn_domain.storable_text import pg_safe

if TYPE_CHECKING:
    from collections.abc import Iterator

    from syn_domain.contexts.artifacts.ports.ArtifactContentStoragePort import (
        ArtifactContentStoragePort,
    )

RECORDED = Path(__file__).parent / "fixtures" / "recorded_artifact_created"

pytestmark = pytest.mark.unit

MARKDOWN = "# Findings\n\nUnicode stays exact: café, 日本語, emoji 🎉, and naïve résumé.\n".encode()
MD_PATH = "artifacts/output/findings.md"
PNG_PATH = "artifacts/output/screenshots/home.png"


def _tiny_png(width: int = 3, height: int = 2) -> bytes:
    """A real, decodable PNG built from the spec, not remembered from anywhere.

    The pixel data is chosen to contain bytes that are invalid UTF-8 (0x89 in
    the signature, 0xFF/0x80 in the pixels), which is exactly what the old
    decode replaced with U+FFFD.
    """

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + bytes((0xFF, 0x80, 0x00)) * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


PNG = _tiny_png()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class _Workspace:
    collected: list[tuple[str, bytes]]
    injected: list[tuple[str, bytes]] = field(default_factory=list)

    async def inject_files(self, files: list[tuple[str, bytes]]) -> None:
        self.injected.extend(files)

    async def collect_files(self, patterns: list[str]) -> list[tuple[str, bytes]]:
        return self.collected


@dataclass
class _Repo:
    saved: list[ArtifactAggregate] = field(default_factory=list)

    async def save(self, aggregate: ArtifactAggregate) -> None:
        self.saved.append(aggregate)


@dataclass
class _ExecutionContext:
    workflow_id: str = "wf-990"
    execution_id: str = "exec-990"
    completed_phase_ids: list[str] = field(default_factory=lambda: ["verify"])
    phase_outputs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class _World:
    storage: ArtifactContentStoragePort
    projection: ArtifactListProjection
    ids: dict[str, str]  # source_path -> artifact id
    collector: ArtifactCollector


async def _collect(storage: ArtifactContentStoragePort | None = None) -> _World:
    """Run the real collector and project what it emitted, as the subscription does."""
    storage = storage or InMemoryArtifactStorage()
    repo = _Repo()
    collector = ArtifactCollector(repo, storage, None)  # type: ignore[arg-type]
    await collector.collect_from_workspace(
        workspace=_Workspace(collected=[(MD_PATH, MARKDOWN), (PNG_PATH, PNG)]),  # type: ignore[arg-type]
        workflow_id="wf-990",
        phase_id="verify",
        execution_id="exec-990",
        session_id="s-990",
        phase_name="Verify",
        output_artifact_types=("markdown",),
        agent=UNREPORTED_AGENT,
    )
    projection = ArtifactListProjection(InMemoryProjectionStore())
    ids: dict[str, str] = {}
    for aggregate in repo.saved:
        for envelope in aggregate.get_uncommitted_events():
            event = envelope.event
            assert isinstance(event, ArtifactCreatedEvent)
            # The projection adapter hands handlers `model_dump()`.
            await projection.on_artifact_created(event.model_dump())
            assert event.source_path is not None
            ids[event.source_path] = event.artifact_id
    return _World(storage=storage, projection=projection, ids=ids, collector=collector)


@pytest.fixture
def api_wired_to() -> Iterator[list[_World]]:
    """Point the API module at the world's projection and storage."""
    holder: list[_World] = []

    def mgr() -> object:
        return type("Mgr", (), {"artifact_list": holder[0].projection, "store": None})()

    async def storage() -> ArtifactContentStoragePort:
        return holder[0].storage

    with (
        patch("syn_api.routes.artifacts.ensure_connected", new=AsyncMock()),
        patch("syn_api.routes.artifacts.get_projection_mgr", side_effect=mgr),
        patch(
            "syn_api.prefix_resolver.resolve_or_raise", new=AsyncMock(side_effect=lambda *a: a[2])
        ),
        patch(
            "syn_adapters.storage.artifact_storage.get_artifact_storage",
            side_effect=storage,
        ),
    ):
        yield holder


class TestCollectionToApi:
    @pytest.mark.asyncio
    async def test_png_and_markdown_round_trip_byte_for_byte(
        self, api_wired_to: list[_World]
    ) -> None:
        world = await _collect()
        api_wired_to.append(world)

        for path, original, media_type in (
            (MD_PATH, MARKDOWN, "text/markdown"),
            (PNG_PATH, PNG, "image/png"),
        ):
            response = await get_artifact_raw_endpoint(world.ids[path])
            assert _sha(bytes(response.body)) == _sha(original), path
            assert response.media_type == media_type, path

    @pytest.mark.asyncio
    async def test_the_png_bytes_never_enter_the_event(self) -> None:
        world = await _collect()
        row = await world.projection.get_by_id(world.ids[PNG_PATH])
        assert row is not None
        assert row.content == ""
        assert row.content_type == "image/png"
        # Hash and size describe the FILE, not a decoding of it.
        assert row.content_hash == _sha(PNG)
        assert row.size_bytes == len(PNG)

    @pytest.mark.asyncio
    async def test_markdown_row_and_hash_are_what_they_always_were(
        self, api_wired_to: list[_World]
    ) -> None:
        world = await _collect()
        api_wired_to.append(world)
        row = await world.projection.get_by_id(world.ids[MD_PATH])
        assert row is not None
        assert row.content == MARKDOWN.decode("utf-8")
        assert row.content_type == "text/markdown"
        # Pre-#990 hashing was sha256(text.encode("utf-8")); for text it is
        # the same number, so every stored hash still verifies.
        assert row.content_hash == _sha(MARKDOWN)

        detail = await get_artifact(world.ids[MD_PATH], include_content=True)
        assert isinstance(detail, Ok)
        assert detail.value.content == MARKDOWN.decode("utf-8")

    @pytest.mark.asyncio
    async def test_json_detail_reports_png_type_and_never_mangled_text(
        self, api_wired_to: list[_World]
    ) -> None:
        world = await _collect()
        api_wired_to.append(world)
        detail = await get_artifact(world.ids[PNG_PATH], include_content=True)
        assert isinstance(detail, Ok)
        assert detail.value.content is None  # no text form; served by /raw
        assert detail.value.content_type == "image/png"


class TestHandoffToTheNextPhase:
    @pytest.mark.asyncio
    async def test_live_path_injects_the_png_bytes(self) -> None:
        """The live path hands `CollectedArtifacts.files` straight on."""
        storage = InMemoryArtifactStorage()
        collector = ArtifactCollector(_Repo(), storage, None)  # type: ignore[arg-type]
        collected = await collector.collect_from_workspace(
            workspace=_Workspace(collected=[(MD_PATH, MARKDOWN), (PNG_PATH, PNG)]),  # type: ignore[arg-type]
            workflow_id="wf-990",
            phase_id="verify",
            execution_id="exec-990",
            session_id="s-990",
            phase_name="Verify",
            output_artifact_types=("markdown",),
            agent=UNREPORTED_AGENT,
        )
        assert collected.first_content == MARKDOWN.decode("utf-8")
        consumer = _Workspace(collected=[])
        await collector.inject_from_previous_phases_explicit(
            consumer,  # type: ignore[arg-type]
            completed_phase_ids=["verify"],
            phase_outputs={"verify": collected.first_content or ""},
            phase_files={"verify": collected.files},
        )
        injected = dict(consumer.injected)
        assert _sha(injected["artifacts/input/verify/screenshots/home.png"]) == _sha(PNG)
        assert _sha(injected["artifacts/input/verify/findings.md"]) == _sha(MARKDOWN)

    @pytest.mark.asyncio
    async def test_restart_path_reads_the_png_from_object_storage(self) -> None:
        """After a restart the files come from the read model, which holds no bytes."""
        world = await _collect()
        query = ArtifactQueryService(world.projection, content_storage=world.storage)
        files = await query.get_files_for_phase_injection("exec-990", ["verify"])
        consumer = _Workspace(collected=[])
        await world.collector.inject_from_previous_phases_explicit(
            consumer,  # type: ignore[arg-type]
            completed_phase_ids=["verify"],
            phase_outputs={},
            phase_files=files,
        )
        injected = dict(consumer.injected)
        assert _sha(injected["artifacts/input/verify/screenshots/home.png"]) == _sha(PNG)
        assert _sha(injected["artifacts/input/verify/findings.md"]) == _sha(MARKDOWN)
        # The flat alias is the phase's TEXT, never the screenshot.
        assert injected["artifacts/input/verify.md"] == MARKDOWN


class TestHistoricalEventsStillReplay:
    #: An ArtifactCreated payload in the exact v6 shape, serialized as the
    #: store holds it (every field v6 declared), from before binary types existed.
    V6_JSON = (
        '{"artifact_id": "art-v6", "workflow_id": "wf-old", '
        '"phase_id": "plan", "execution_id": "exec-old", '
        '"session_id": "s-old", "artifact_type": "markdown", '
        '"content_type": "text/markdown", "content": "# Plan\\nstep one", '
        '"content_hash": "93df2525f1aae66e705a937c18d1f99f108f87636f5a82352676d8647531d27d", '
        '"size_bytes": 15, "title": "Plan: artifacts/output/plan.md", '
        '"storage_uri": null, "is_primary_deliverable": true, '
        '"derived_from": [], "metadata": {}, '
        '"source_path": "artifacts/output/plan.md", '
        '"agent_provider": "claude", "agent_model": "claude-opus-5-5", '
        '"created_at": "2026-09-30T12:00:00+00:00"}'
    )

    @pytest.mark.asyncio
    async def test_v6_payload_replays_into_aggregate_and_projection(self) -> None:
        event = ArtifactCreatedEvent.model_validate_json(self.V6_JSON)
        assert event.content_type is ContentType.TEXT_MARKDOWN
        assert not event.content_type.is_binary

        aggregate = ArtifactAggregate()
        aggregate.on_artifact_created(event)
        assert aggregate.content == "# Plan\nstep one"

        projection = ArtifactListProjection(InMemoryProjectionStore())
        await projection.on_artifact_created(json.loads(self.V6_JSON))
        row = await projection.get_by_id("art-v6")
        assert row is not None
        assert row.content == "# Plan\nstep one"
        assert row.content_hash == hashlib.sha256(b"# Plan\nstep one").hexdigest()

    @pytest.mark.asyncio
    async def test_a_row_projected_before_content_type_was_kept_is_text(self) -> None:
        """Rows from read-model v6 have no content_type; they are handed on as text."""
        store = InMemoryProjectionStore()
        projection = ArtifactListProjection(store)
        payload = json.loads(self.V6_JSON)
        del payload["content_type"]
        await projection.on_artifact_created(payload)
        files = await ArtifactQueryService(projection).get_files_for_phase_injection(
            "exec-old", ["plan"]
        )
        assert [f.content for f in files["plan"]] == ["# Plan\nstep one"]


def _replayed(payload: bytes) -> ArtifactCreatedEvent:
    """Deserialize stored bytes exactly as a replay does: the ESP client's own path.

    `_proto_to_envelope` falls back to `GenericDomainEvent` when the concrete
    model refuses a payload, silently. So the assertion that matters is the
    TYPE: a historical event that no longer validates would still "replay",
    into a shape no handler reads.
    """
    data = eventstore_pb2.EventData(
        meta=eventstore_pb2.EventMetadata(
            event_id="e-recorded",
            aggregate_id="a-recorded",
            aggregate_type="Artifact",
            aggregate_nonce=1,
            event_type="ArtifactCreated",
            event_version=1,
            content_type="application/json",
        ),
        payload=payload,
    )
    envelope = GrpcEventStoreClient()._proto_to_envelope(data)
    event = envelope.event
    assert isinstance(event, ArtifactCreatedEvent), type(event).__name__
    return event


class TestRecordedEventsStillReplay:
    """Payloads copied byte-for-byte from a real store, not written for the test.

    Provenance: the dev event store (`events.payload`, `event_version` 1),
    global nonces 861 (2026-08-28, a text artifact) and 46 (2026-07-25, a
    `.pyc` an agent wrote, stored as U+FFFD text by the pre-#990 decode).
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "name", ["v1-text-2026-08-28.json", "v1-binary-decoded-as-text-2026-07-25.json"]
    )
    async def test_recorded_payload_replays_through_aggregate_projection_and_api(
        self, name: str, api_wired_to: list[_World]
    ) -> None:
        payload = (RECORDED / name).read_bytes()
        event = _replayed(payload)
        # Pre-#990 events are all text, and stay text: nothing re-reads them.
        assert event.content_type is ContentType.TEXT_MARKDOWN
        assert event.content

        aggregate = ArtifactAggregate()
        aggregate.on_artifact_created(event)
        assert aggregate.content == event.content

        projection = ArtifactListProjection(InMemoryProjectionStore())
        await projection.on_artifact_created(event.model_dump())
        row = await projection.get_by_id(event.artifact_id)
        assert row is not None
        # The projection store makes NUL storable, as PostgreSQL JSONB needs;
        # pre-#990 that was all the handling a decoded binary file ever got.
        assert row.content == pg_safe(event.content)
        assert row.content_type == "text/markdown"
        # The stored hash still verifies under the new hashing: sha256 of the
        # text's UTF-8 - for the mangled .pyc, of the U+FFFD text it became.
        assert compute_content_hash(event.content) == event.content_hash

        # Served from the read model when object storage has nothing for it.
        api_wired_to.append(
            _World(
                storage=InMemoryArtifactStorage(),
                projection=projection,
                ids={},
                collector=ArtifactCollector(_Repo(), None, None),  # type: ignore[arg-type]
            )
        )
        response = await get_artifact_raw_endpoint(event.artifact_id)
        assert bytes(response.body) == row.content.encode("utf-8")


class TestPrimaryDeliverableIsNeverAScreenshot:
    """The head of a phase's output is flagged primary; glob order is arbitrary."""

    @pytest.mark.asyncio
    async def test_completed_phase_flags_the_text_even_when_the_png_is_listed_first(
        self,
    ) -> None:
        repo = _Repo()
        collector = ArtifactCollector(repo, InMemoryArtifactStorage(), None)  # type: ignore[arg-type]
        await collector.collect_from_workspace(
            workspace=_Workspace(collected=[(PNG_PATH, PNG), (MD_PATH, MARKDOWN)]),  # type: ignore[arg-type]
            workflow_id="wf-990",
            phase_id="verify",
            execution_id="exec-990",
            session_id="s-990",
            phase_name="Verify",
            output_artifact_types=("markdown",),
            agent=UNREPORTED_AGENT,
        )
        assert _primary_flags(repo) == {MD_PATH: True, PNG_PATH: False}

    @pytest.mark.asyncio
    async def test_unfinished_phase_flags_the_text_even_when_the_png_is_listed_first(
        self,
    ) -> None:
        repo = _Repo()
        collector = ArtifactCollector(repo, InMemoryArtifactStorage(), None)  # type: ignore[arg-type]
        await collector.collect_from_unfinished_phase(
            workspace=_Workspace(collected=[(PNG_PATH, PNG), (MD_PATH, MARKDOWN)]),  # type: ignore[arg-type]
            workflow_id="wf-990",
            phase_id="verify",
            execution_id="exec-990",
            session_id="s-990",
            phase_name="Verify",
            output_artifact_types=("markdown",),
            agent=UNREPORTED_AGENT,
            outcome=UnfinishedPhase.INTERRUPTED,
        )
        assert _primary_flags(repo) == {MD_PATH: True, PNG_PATH: False}


def _primary_flags(repo: _Repo) -> dict[str, bool]:
    flags: dict[str, bool] = {}
    for aggregate in repo.saved:
        for envelope in aggregate.get_uncommitted_events():
            event = envelope.event
            assert isinstance(event, ArtifactCreatedEvent)
            assert event.source_path is not None
            flags[event.source_path] = event.is_primary_deliverable
    return flags


class TestBinaryBytesNeverEnterTheEventStore:
    """The aggregate refuses every shape that would put bytes in Lane 1 or lose them."""

    @staticmethod
    def _command(
        content: str | bytes, content_type: ContentType, storage_uri: str | None
    ) -> CreateArtifactCommand:
        return CreateArtifactCommand(
            workflow_id="wf-990",
            phase_id="verify",
            artifact_type=ArtifactType.OTHER,
            content_type=content_type,
            content=content,
            storage_uri=storage_uri,
        )

    @pytest.mark.parametrize(
        ("content", "content_type", "storage_uri", "refusal"),
        [
            (PNG, ContentType.IMAGE_PNG, None, "object storage"),
            (PNG, ContentType.TEXT_MARKDOWN, "s3://b/k", "must be str"),
            ("# text", ContentType.IMAGE_PNG, "s3://b/k", "must be bytes"),
        ],
        ids=["png-without-storage", "bytes-as-text", "text-as-png"],
    )
    def test_refused(
        self, content: str | bytes, content_type: ContentType, storage_uri: str | None, refusal: str
    ) -> None:
        with pytest.raises(ValueError, match=refusal):
            ArtifactAggregate().create_artifact(self._command(content, content_type, storage_uri))

    @pytest.mark.asyncio
    async def test_no_object_storage_fails_loudly_instead_of_mangling(self) -> None:
        repo = _Repo()
        collector = ArtifactCollector(repo, None, None)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="object storage"):
            await collector.collect_from_workspace(
                workspace=_Workspace(collected=[(PNG_PATH, PNG)]),  # type: ignore[arg-type]
                workflow_id="wf-990",
                phase_id="verify",
                execution_id="exec-990",
                session_id="s-990",
                phase_name="Verify",
                output_artifact_types=("markdown",),
                agent=UNREPORTED_AGENT,
            )
        assert repo.saved == []


@dataclass
class _KeyedObjectStore:
    """An S3 bucket as `MinioArtifactStorage` sees it: bytes by full object key.

    The in-memory artifact storage keys by artifact id alone, which is what hid
    the defect this pins: MinIO keys an upload by workflow and execution too,
    so a read by id alone found nothing and every binary artifact 404'd.
    """

    _bucket_name: str = "syn-artifacts"
    objects: dict[str, bytes] = field(default_factory=dict)

    async def upload(
        self, key: str, content: bytes, *, content_type: str, metadata: dict[str, str]
    ) -> UploadResult:
        self.objects[key] = content
        return UploadResult(key=key, size_bytes=len(content))

    async def download(self, key: str) -> bytes:
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return self.objects[key]


class TestMinioKeyLayout:
    """The real MinIO artifact adapter, over a bucket keyed the way MinIO keys it."""

    @staticmethod
    def _storage() -> MinioArtifactStorage:
        return MinioArtifactStorage(_KeyedObjectStore())  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_api_serves_both_files_byte_for_byte(self, api_wired_to: list[_World]) -> None:
        world = await _collect(self._storage())
        api_wired_to.append(world)
        for path, original in ((MD_PATH, MARKDOWN), (PNG_PATH, PNG)):
            response = await get_artifact_raw_endpoint(world.ids[path])
            assert _sha(bytes(response.body)) == _sha(original), path

    @pytest.mark.asyncio
    async def test_restart_handoff_reads_the_png_from_where_it_was_uploaded(self) -> None:
        world = await _collect(self._storage())
        query = ArtifactQueryService(world.projection, content_storage=world.storage)
        files = await query.get_files_for_phase_injection("exec-990", ["verify"])
        by_path = {f.source_path: f.content for f in files["verify"]}
        assert by_path[PNG_PATH] == PNG
