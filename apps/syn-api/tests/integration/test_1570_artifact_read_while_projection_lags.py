"""An artifact is readable by id while its read model lags (#1570).

THE INCIDENT. ``GET /artifacts/{id}`` and ``/content`` answered 404 for an
artifact whose 34,621 characters were in MinIO: the routes resolved the id
through ``artifact_summaries`` alone, and that projection had not caught up.
Recovering the content took ssh and ``docker exec`` into MinIO.

WHAT IS REAL HERE. The event store (the artifact is created through
``CreateArtifactHandler`` and saved to it), MinIO (the bytes are uploaded under
the workflow/execution/artifact key that broke #1652), the subscription
(``CoordinatorSubscriptionService`` delivering to ``ArtifactListProjection``
with its own checkpoint) and the three route functions with their prefix
resolution.

"BEHIND" IS A HELD CHECKPOINT. The projection is subscribed before the artifact
is created, and the coordinator does deliver ``ArtifactCreated`` to it, but its
handler is held at the door: it neither writes the row nor saves the
checkpoint until the test lets go. Each test asserts the event was delivered,
the ``artifact_summaries`` checkpoint is still short of the event's global
position and the row is absent, then reads. Afterwards the hold is released
and the same subscription moves the checkpoint past the event and writes the
row with the same storage key, so the projection under test was genuinely
behind, not a stand-in that could never have a row.

MinIO is the test stack's (``TEST_MINIO_URL``, default ``localhost:19000``)
when one answers, otherwise a throwaway container. Skips, never passes, when
there is neither.
"""

from __future__ import annotations

import asyncio
import os
import socket
from contextlib import AsyncExitStack, contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from event_sourcing import EventStoreRepository
from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore
from fastapi import HTTPException

from syn_adapters.object_storage.minio import MinioStorage
from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.artifact_storage.minio import MinioArtifactStorage
from syn_adapters.storage.legacy_tolerant_client import LegacyShapeTolerantGrpcClient
from syn_adapters.storage.repositories import RepositoryAdapter
from syn_adapters.subscriptions.coordinator_service import CoordinatorSubscriptionService
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

    from event_sourcing import (
        DispatchContext,
        DomainEvent,
        EventEnvelope,
        ProjectionCheckpointStore,
        ProjectionResult,
    )
    from syn_tests.fixtures.infrastructure import TestInfrastructure

pytestmark = pytest.mark.integration

#: The size of the artifact that went missing, so the body is not trivially short.
FINDINGS = "# Findings\n\n" + "x" * 34_609
#: Not valid UTF-8: survives only byte-for-byte, and only from object storage.
SCREENSHOT = bytes(range(256)) * 4
#: The image the compose stacks run, so the container matches what ships.
MINIO_IMAGE = (
    "ghcr.io/syntropic137/minio:RELEASE.2025-04-22T22-12-26Z"
    "@sha256:bbac678936882e4033b6068efd0a19d103b219002d979087f7c5bd330172e00d"
)
#: How long a released subscription may take to apply one held event.
CATCH_UP_S = 10.0


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


class _HeldArtifactList(ArtifactListProjection):
    """``ArtifactListProjection`` whose handler waits at the door until released.

    The coordinator delivers to it as to any projection. While held, nothing
    the real handler does has happened: no row, no checkpoint save.
    """

    def __init__(self, store: InMemoryProjectionStore) -> None:
        super().__init__(store)
        self.delivered = asyncio.Event()
        self.released = asyncio.Event()

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,
    ) -> ProjectionResult:
        self.delivered.set()
        await self.released.wait()
        return await super().handle_event(envelope, checkpoint_store, context)


@dataclass(frozen=True)
class _ProjectionManager:
    """The two members of the projection manager the artifact routes read."""

    store: InMemoryProjectionStore
    artifact_list: ArtifactListProjection


class _World:
    """One event-store tenant, one bucket, and a subscribed projection held behind."""

    #: The checkpoint the hold keeps behind.
    PROJECTION: ClassVar[str] = "artifact_summaries"

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
        self.projection = _HeldArtifactList(self.store)
        assert self.projection.get_name() == self.PROJECTION
        self.checkpoints = MemoryCheckpointStore()
        self.subscription = CoordinatorSubscriptionService(
            event_store=client,
            projections=[self.projection],
            checkpoint_store=self.checkpoints,
        )
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

    async def created_at(self, artifact_id: str) -> int:
        """The global position of the artifact's ArtifactCreated in the event store."""
        events = await self.client.read_events(f"Artifact-{artifact_id}")
        assert events, f"no Artifact-{artifact_id} stream in the event store"
        nonce = events[0].metadata.global_nonce
        assert nonce is not None
        return nonce

    async def checkpoint(self) -> int | None:
        saved = await self.checkpoints.get_checkpoint(self.PROJECTION)
        return None if saved is None else saved.global_position

    async def assert_held_behind(self, artifact_id: str) -> int:
        """The event reached the projection; its checkpoint and row did not move."""
        position = await self.created_at(artifact_id)
        await asyncio.wait_for(self.projection.delivered.wait(), CATCH_UP_S)
        held = await self.checkpoint()
        assert held is None or held < position, (held, position)
        assert await self.projection.get_by_id(artifact_id) is None
        return position

    async def release_checkpoint(self, position: int) -> None:
        """Let the subscription apply what it holds, and wait until it has."""
        self.projection.released.set()
        async with asyncio.timeout(CATCH_UP_S):
            while (await self.checkpoint() or 0) < position:
                await asyncio.sleep(0.05)

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


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
    except Exception:
        return False
    return True


@pytest.fixture(scope="module")
def minio_endpoint() -> Iterator[str]:
    """The test stack's MinIO when it answers, otherwise a container of our own."""
    endpoint = _minio_endpoint()
    if _reachable(endpoint):
        yield endpoint
        return
    if not _docker_available():
        pytest.skip(f"no MinIO at {endpoint} (set {ENV_TEST_MINIO_URL}) and no Docker to start one")
    from testcontainers.minio import MinioContainer

    with MinioContainer(
        MINIO_IMAGE,
        access_key=os.getenv("TEST_MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("TEST_MINIO_SECRET_KEY", "minioadmin"),
    ) as container:
        yield str(container.get_config()["endpoint"])


@pytest.fixture
async def world(
    test_infrastructure: TestInfrastructure, minio_endpoint: str
) -> AsyncIterator[_World]:
    storage = MinioArtifactStorage(
        MinioStorage(
            endpoint=minio_endpoint,
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
    world = _World(client, storage)
    async with AsyncExitStack() as cleanup:
        cleanup.push_async_callback(client.disconnect)
        await world.subscription.start()
        cleanup.push_async_callback(world.subscription.stop)
        # Unblock a handler a failed test left waiting, so stop() is not stuck on it.
        cleanup.callback(world.projection.released.set)
        yield world


async def test_a_text_artifact_reads_by_id_and_content_while_the_projection_lags(
    world: _World,
) -> None:
    artifact_id, storage_uri = await world.create(FINDINGS, ContentType.TEXT_MARKDOWN)
    position = await world.assert_held_behind(artifact_id)

    with world.serving():
        detail = await get_artifact_endpoint(artifact_id, include_content=True)
        content = await get_artifact_content_endpoint(artifact_id)

    assert detail.id == artifact_id
    assert detail.content == FINDINGS
    assert content.content == FINDINGS

    await world.release_checkpoint(position)
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
    position = await world.assert_held_behind(artifact_id)

    with world.serving():
        raw = await get_artifact_raw_endpoint(artifact_id)

    assert raw.status_code == 200
    assert raw.body == SCREENSHOT
    assert raw.media_type == ContentType.IMAGE_PNG.value

    await world.release_checkpoint(position)
    caught_up = await world.projection.get_by_id(artifact_id)
    assert caught_up is not None
    assert caught_up.storage_uri == storage_uri


async def test_an_artifact_that_was_never_created_is_still_not_found(world: _World) -> None:
    with world.serving(), pytest.raises(HTTPException) as raised:
        await get_artifact_endpoint(str(uuid4()), include_content=True)
    assert raised.value.status_code == 404
