"""An artifact is readable by id while its read model lags (#1570).

THE INCIDENT. ``GET /artifacts/{id}`` and ``/content`` answered 404 for an
artifact whose 34,621 characters were in MinIO: the routes resolved the id
through ``artifact_summaries`` alone, and that projection had not caught up.
Recovering the content took ssh and ``docker exec`` into MinIO.

WHAT IS REAL HERE. The event store (the artifact is created through
``CreateArtifactHandler`` and saved to it), MinIO (the bytes are uploaded under
the workflow/execution/artifact key that broke #1652), the projection
(``ArtifactListProjection``) and the three route functions with their prefix
resolution.

"BEHIND" IS A HELD CHECKPOINT. The projection is the real one over a real
store, but no subscription delivers to it: it sits at the position it held
before the artifact was created. Each test asserts its row is absent before
reading, so none passes by finding it. Afterwards the checkpoint is released
-- the stored events are read back from the event store and applied -- and the
same projection answers with the same storage key, so the projection under
test was genuinely behind, not a stand-in that could never have a row.

Needs the test stack's event store and MinIO (``TEST_MINIO_URL``, default
``localhost:19000``). Skips, never passes, when MinIO does not answer.
"""

from __future__ import annotations

import os
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from event_sourcing import EventStoreRepository
from fastapi import HTTPException

from syn_adapters.object_storage.minio import MinioStorage
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.artifact_storage.minio import MinioArtifactStorage
from syn_adapters.storage.legacy_tolerant_client import LegacyShapeTolerantGrpcClient
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_api.routes.artifacts import (
    get_artifact_content_endpoint,
    get_artifact_endpoint,
    get_artifact_raw_endpoint,
)
from syn_domain.contexts.artifacts import (
    ArtifactAggregate,
    ArtifactType,
    ContentType,
    CreateArtifactCommand,
    CreateArtifactHandler,
)
from syn_domain.contexts.artifacts.slices.list_artifacts.projection import (
    ArtifactListProjection,
)
from syn_shared.testing import ENV_TEST_MINIO_URL, TEST_STACK_PORTS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

#: The size of the artifact that went missing, so the body is not trivially short.
FINDINGS = "# Findings\n\n" + "x" * 34_609
#: Not valid UTF-8: survives only byte-for-byte, and only from object storage.
SCREENSHOT = bytes(range(256)) * 4


def _minio_endpoint() -> str:
    raw = os.getenv(ENV_TEST_MINIO_URL, f"localhost:{TEST_STACK_PORTS['minio_api']}")
    return raw.removeprefix("http://").removeprefix("https://").rstrip("/")


def _reachable(endpoint: str) -> bool:
    host, _, port = endpoint.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=1):
            return True
    except OSError:
        return False


@dataclass(frozen=True)
class _ProjectionManager:
    """The two members of the projection manager the artifact routes read."""

    store: InMemoryProjectionStore
    artifact_list: ArtifactListProjection


class _World:
    """One event-store tenant, one bucket, and a projection nobody feeds."""

    def __init__(self, client: LegacyShapeTolerantGrpcClient, storage: MinioArtifactStorage):
        self.client = client
        self.storage = storage
        self.repository = RepositoryAdapter(
            EventStoreRepository(
                client,
                ArtifactAggregate,  # type: ignore[arg-type]  # ESP SDK TEvent invariance
                "Artifact",
            )
        )
        self.store = InMemoryProjectionStore()
        self.projection = ArtifactListProjection(self.store)
        self.workflow_id = f"wf-1570-{uuid4().hex[:8]}"
        self.execution_id = f"exec-1570-{uuid4().hex[:8]}"

    async def create(self, content: str | bytes, content_type: ContentType) -> tuple[str, str]:
        """Upload, then record the artifact, the order the collector uses. -> (id, uri)."""
        artifact_id = str(uuid4())
        data = content.encode("utf-8") if isinstance(content, str) else content
        uploaded = await self.storage.upload(
            artifact_id,
            data,
            workflow_id=self.workflow_id,
            phase_id="research",
            execution_id=self.execution_id,
            content_type=content_type.value,
        )
        await CreateArtifactHandler(self.repository).handle(
            CreateArtifactCommand(
                aggregate_id=artifact_id,
                workflow_id=self.workflow_id,
                execution_id=self.execution_id,
                phase_id="research",
                artifact_type=ArtifactType.RESEARCH_SUMMARY,
                content_type=content_type,
                content=content,
                title="Research findings",
                storage_uri=uploaded.storage_uri,
            )
        )
        return artifact_id, uploaded.storage_uri

    async def release_checkpoint(self, artifact_id: str) -> None:
        """Deliver what the event store holds to the projection, as a subscription would."""
        events = await self.client.read_events(f"Artifact-{artifact_id}")
        assert events, f"no Artifact-{artifact_id} stream in the event store"
        for envelope in events:
            await self.projection.on_artifact_created(envelope.event.model_dump())

    @contextmanager
    def serving(self) -> Iterator[None]:
        """The API's wiring, pointed at this event store, bucket and projection."""
        manager = _ProjectionManager(store=self.store, artifact_list=self.projection)
        with (
            patch("syn_api.routes.artifacts.ensure_connected", new=AsyncMock()),
            patch("syn_api.routes.artifacts.get_projection_mgr", return_value=manager),
            patch("syn_api.routes.artifacts.get_artifact_repo", return_value=self.repository),
            patch(
                "syn_adapters.storage.artifact_storage.get_artifact_storage",
                new=AsyncMock(return_value=self.storage),
            ),
        ):
            yield


@pytest.fixture
async def world(test_infrastructure: TestInfrastructure) -> AsyncIterator[_World]:
    endpoint = _minio_endpoint()
    if not _reachable(endpoint):
        pytest.skip(f"no MinIO at {endpoint} (set {ENV_TEST_MINIO_URL})")
    storage = MinioArtifactStorage(
        MinioStorage(
            endpoint=endpoint,
            access_key=os.getenv("TEST_MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("TEST_MINIO_SECRET_KEY", "minioadmin"),
            bucket_name=f"artifacts-1570-{uuid4().hex[:16]}",
            secure=False,
        )
    )
    await storage.ensure_ready()
    client = LegacyShapeTolerantGrpcClient(
        address=f"{test_infrastructure.eventstore_host}:{test_infrastructure.eventstore_port}",
        tenant_id=f"t-1570-{uuid4().hex}",
    )
    await client.connect()
    try:
        yield _World(client, storage)
    finally:
        await client.disconnect()


async def test_a_text_artifact_reads_by_id_and_content_while_the_projection_lags(
    world: _World,
) -> None:
    artifact_id, storage_uri = await world.create(FINDINGS, ContentType.TEXT_MARKDOWN)
    assert await world.projection.get_by_id(artifact_id) is None

    with world.serving():
        detail = await get_artifact_endpoint(artifact_id, include_content=True)
        content = await get_artifact_content_endpoint(artifact_id)

    assert detail.id == artifact_id
    assert detail.content == FINDINGS
    assert content.content == FINDINGS

    await world.release_checkpoint(artifact_id)
    caught_up = await world.projection.get_by_id(artifact_id)
    assert caught_up is not None
    assert caught_up.storage_uri == storage_uri


async def test_a_binary_artifact_reads_raw_from_its_scoped_storage_key_while_the_projection_lags(
    world: _World,
) -> None:
    """The bytes are ONLY in MinIO, under the workflow/execution key (#1652).

    The aggregate records no inline content for a binary artifact, so the only
    way to answer is the storage_uri the aggregate carries; a key rebuilt from
    the artifact id alone names an object that does not exist.
    """
    artifact_id, storage_uri = await world.create(SCREENSHOT, ContentType.IMAGE_PNG)
    assert f"/{world.workflow_id}/{world.execution_id}/" in storage_uri
    assert await world.projection.get_by_id(artifact_id) is None

    with world.serving():
        raw = await get_artifact_raw_endpoint(artifact_id)

    assert raw.status_code == 200
    assert raw.body == SCREENSHOT
    assert raw.media_type == ContentType.IMAGE_PNG.value


async def test_an_artifact_that_was_never_created_is_still_not_found(world: _World) -> None:
    with world.serving(), pytest.raises(HTTPException) as raised:
        await get_artifact_endpoint(str(uuid4()), include_content=True)
    assert raised.value.status_code == 404
