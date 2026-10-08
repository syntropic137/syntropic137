"""One contract, two artifact content stores (#990, #1652).

Every test here runs against InMemoryArtifactStorage (unit) AND
MinioArtifactStorage against a real MinIO (integration). The in-memory
store stands in for MinIO in every unit test that reads an artifact, so it
is only worth having while it answers the way MinIO does.

The keyspace is what broke production: MinIO keys an object by
``artifacts/{workflow_id}/{execution_id}/{artifact_id}.md``, the fake keyed
by artifact id alone, and every unit test read back what MinIO 404'd. Read
paths therefore find content by the ``storage_uri`` upload returned, and
these tests read the way those paths do.

The integration half needs MinIO: ``TEST_MINIO_URL`` (default the test
stack's ``localhost:19000``), credentials ``TEST_MINIO_ACCESS_KEY`` /
``TEST_MINIO_SECRET_KEY`` (default ``minioadmin``). It skips, never passes,
when MinIO does not answer.
"""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from syn_adapters.object_storage.minio import MinioStorage
from syn_adapters.storage.artifact_storage.memory import InMemoryArtifactStorage
from syn_adapters.storage.artifact_storage.minio import MinioArtifactStorage
from syn_domain.contexts.artifacts.ports import ArtifactStorageError
from syn_shared.testing import ENV_TEST_MINIO_URL, TEST_STACK_PORTS

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

ArtifactStorage = InMemoryArtifactStorage | MinioArtifactStorage

BINARY = bytes(range(256)) * 4  # not valid UTF-8: survives only byte-for-byte


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


@pytest.fixture(
    params=[
        pytest.param("memory", marks=pytest.mark.unit),
        pytest.param("minio", marks=pytest.mark.integration),
    ]
)
async def storage(request: pytest.FixtureRequest) -> AsyncIterator[ArtifactStorage]:
    if request.param == "memory":
        yield InMemoryArtifactStorage()
        return
    endpoint = _minio_endpoint()
    if not _reachable(endpoint):
        pytest.skip(f"no MinIO at {endpoint} (set {ENV_TEST_MINIO_URL})")
    minio = MinioArtifactStorage(
        MinioStorage(
            endpoint=endpoint,
            access_key=os.getenv("TEST_MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("TEST_MINIO_SECRET_KEY", "minioadmin"),
            bucket_name=f"contract-{uuid4().hex[:20]}",
            secure=False,
        )
    )
    await minio.ensure_ready()
    yield minio


def _id() -> str:
    return f"artifact-{uuid4().hex}"


async def test_content_uploaded_with_its_execution_is_read_back_via_storage_uri(
    storage: ArtifactStorage,
) -> None:
    """How the read model reads (#1652): by the storage_uri upload returned."""
    artifact_id = _id()
    result = await storage.upload(
        artifact_id, BINARY, workflow_id="wf-contract", execution_id="exec-contract"
    )

    assert await storage.download(artifact_id, storage_uri=result.storage_uri) == BINARY


async def test_content_uploaded_with_its_execution_is_not_at_the_id_alone(
    storage: ArtifactStorage,
) -> None:
    """The #990 divergence: the id alone does not find a scoped upload."""
    artifact_id = _id()
    await storage.upload(artifact_id, b"scoped", workflow_id="wf-contract", execution_id="exec-1")

    with pytest.raises(ArtifactStorageError):
        await storage.download(artifact_id)
    assert not await storage.exists(artifact_id)


async def test_same_artifact_id_under_two_executions_is_two_objects(
    storage: ArtifactStorage,
) -> None:
    artifact_id = _id()
    first = await storage.upload(artifact_id, b"first", workflow_id="wf", execution_id="exec-1")
    second = await storage.upload(artifact_id, b"second", workflow_id="wf", execution_id="exec-2")

    assert first.storage_uri != second.storage_uri
    assert await storage.download(artifact_id, storage_uri=first.storage_uri) == b"first"
    assert await storage.download(artifact_id, storage_uri=second.storage_uri) == b"second"


async def test_unscoped_upload_is_found_by_id(storage: ArtifactStorage) -> None:
    """The API upload endpoint uploads with neither id, and reads by id."""
    artifact_id = _id()
    result = await storage.upload(artifact_id, BINARY)

    assert await storage.exists(artifact_id)
    assert await storage.download(artifact_id) == BINARY
    assert await storage.download(artifact_id, storage_uri=result.storage_uri) == BINARY
    assert result.size_bytes == len(BINARY)


async def test_delete_removes_an_unscoped_upload(storage: ArtifactStorage) -> None:
    artifact_id = _id()
    await storage.upload(artifact_id, b"gone soon")

    await storage.delete(artifact_id)

    assert not await storage.exists(artifact_id)


async def test_unknown_artifact_is_not_found(storage: ArtifactStorage) -> None:
    with pytest.raises(ArtifactStorageError):
        await storage.download(_id())
