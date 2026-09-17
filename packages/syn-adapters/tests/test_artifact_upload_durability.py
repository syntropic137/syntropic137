"""An artifact's metadata event must not outrun its bytes (#700).

`ArtifactCreatedEvent` carries a `storage_uri`. A consumer that reacts to the
event and fetches that URI straight away was getting a 404 or a short object,
because `put_object` returning only means the backend accepted the write.

These tests drive the real chain - `ArtifactCollector` -> `MinioArtifactStorage`
-> `MinioStorage` - against a client that reproduces the window, and assert
from the position of that consumer rather than from either end of it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from syn_adapters.object_storage import MinioStorage, UploadError, minio_helpers
from syn_adapters.storage.artifact_storage.minio import MinioArtifactStorage
from syn_adapters.storage.artifact_storage.minio_helpers import parse_s3_key
from syn_domain.contexts.artifacts import UNREPORTED_AGENT
from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
    ArtifactCollector,
)

if TYPE_CHECKING:
    import io
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

BUCKET = "syn-artifacts"
CONTENT = "# Deliverable\nthe bytes a consumer will ask for"
EXPECTED_BYTES = CONTENT.encode("utf-8")


class _NoSuchKey(Exception):
    """What an S3-compatible backend answers for an object it cannot serve."""

    def __init__(self, key: str) -> None:
        super().__init__(f"NoSuchKey: {key} does not exist")


class _Stat:
    def __init__(self, size: int) -> None:
        self.size = size


class _PutResult:
    def __init__(self, etag: str) -> None:
        self.etag = etag


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def close(self) -> None:
        return None

    def release_conn(self) -> None:
        return None


class _LaggingMinio:
    """A MinIO client whose accepted writes are not immediately readable.

    `reads_before_visible` is how many read attempts answer "not there" before
    the object appears; `None` means it never does. Counting READS rather than
    seconds is what makes this an ordering test instead of a race against a
    clock: whoever reads first is the one that meets the gap, so a caller that
    publishes before confirming is the caller that gets caught.

    `truncated_reads` is the other half of the same window - the object is
    there, but short. A consumer cannot tell that from a complete read without
    knowing the expected size.
    """

    def __init__(
        self,
        *,
        reads_before_visible: int | None = 0,
        truncated_reads: int = 0,
    ) -> None:
        self._reads_before_visible = reads_before_visible
        self._truncated_reads = truncated_reads
        self._objects: dict[str, bytes] = {}
        self._pending_reads: dict[str, int] = {}
        self._pending_truncations: dict[str, int] = {}
        self.reads: list[str] = []

    def bucket_exists(self, bucket_name: str) -> bool:
        return True

    def make_bucket(self, bucket_name: str) -> None:
        raise AssertionError(f"bucket {bucket_name} should already exist")

    def put_object(
        self,
        bucket_name: str,
        key: str,
        data: io.BytesIO,
        length: int,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> _PutResult:
        self._objects[key] = data.read()
        if self._reads_before_visible is None:
            self._pending_reads[key] = -1  # never becomes visible
        else:
            self._pending_reads[key] = self._reads_before_visible
        self._pending_truncations[key] = self._truncated_reads
        return _PutResult(etag="etag-for-" + key)

    def _serve(self, key: str) -> bytes | None:
        """What this read sees, consuming one step of the window."""
        self.reads.append(key)
        if key not in self._objects:
            return None
        pending = self._pending_reads.get(key, 0)
        if pending != 0:
            if pending > 0:
                self._pending_reads[key] = pending - 1
            return None
        truncations = self._pending_truncations.get(key, 0)
        if truncations > 0:
            self._pending_truncations[key] = truncations - 1
            return self._objects[key][:1]
        return self._objects[key]

    def stat_object(self, bucket_name: str, key: str) -> _Stat:
        payload = self._serve(key)
        if payload is None:
            raise _NoSuchKey(key)
        return _Stat(size=len(payload))

    def get_object(self, bucket_name: str, key: str) -> _Response:
        payload = self._serve(key)
        if payload is None:
            raise _NoSuchKey(key)
        return _Response(payload)


class _FetchingRepository:
    """An event consumer, standing where the projection and the API stand.

    Saving is the moment `ArtifactCreatedEvent` becomes visible, so this does
    what #700 says such a consumer does: reads the `storage_uri` off the event
    and fetches it immediately. What it got is the assertion.
    """

    def __init__(self, storage: MinioStorage) -> None:
        self._storage = storage
        self.fetched: list[bytes] = []
        self.failures: list[str] = []
        self.uris: list[str | None] = []

    async def save(self, aggregate: object) -> None:
        for envelope in aggregate.get_uncommitted_events():  # type: ignore[attr-defined]
            uri = getattr(envelope.event, "storage_uri", None)
            self.uris.append(uri)
            if uri is None:
                continue
            key = parse_s3_key(uri)
            assert key is not None, f"unparseable storage_uri: {uri}"
            try:
                self.fetched.append(await self._storage.download(key))
            except Exception as exc:  # the failure IS the finding
                self.failures.append(f"{type(exc).__name__}: {exc}")


def _storage_for(client: _LaggingMinio) -> MinioStorage:
    storage = MinioStorage(
        endpoint="localhost:9000",
        access_key="test",
        secret_key="test",
        bucket_name=BUCKET,
        secure=False,
    )
    storage._client = client  # type: ignore[assignment] # the client seam
    return storage


async def _collect_one(repo: _FetchingRepository, storage: MinioStorage) -> None:
    collector = ArtifactCollector(
        repository=repo,
        content_storage=MinioArtifactStorage(storage),
        query_service=None,
    )
    await collector.create_artifact(
        artifact_id="artifact-700",
        workflow_id="wf-1",
        phase_id="phase-1",
        execution_id="exec-1",
        session_id="sess-1",
        artifact_type="report",
        content=CONTENT,
        title="Deliverable",
        agent=UNREPORTED_AGENT,
    )


@pytest.fixture
def short_budget(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep the never-readable case from spending the real 10s budget."""
    monkeypatch.setattr(minio_helpers, "READABLE_TIMEOUT_SECONDS", 0.3)
    yield


async def test_consumer_of_the_created_event_can_read_the_bytes() -> None:
    """The event's storage_uri resolves the moment the event exists.

    The window is one read wide, so whoever reads first absorbs it. Publishing
    before confirming makes that first reader the consumer.
    """
    client = _LaggingMinio(reads_before_visible=1)
    storage = _storage_for(client)
    repo = _FetchingRepository(storage)

    await _collect_one(repo, storage)

    assert repo.uris == ["s3://syn-artifacts/artifacts/wf-1/exec-1/artifact-700.md"]
    assert repo.failures == []
    assert repo.fetched == [EXPECTED_BYTES]


async def test_consumer_is_not_handed_a_short_object() -> None:
    """A truncated read is the same broken promise as a missing one."""
    client = _LaggingMinio(truncated_reads=1)
    storage = _storage_for(client)
    repo = _FetchingRepository(storage)

    await _collect_one(repo, storage)

    assert repo.failures == []
    assert repo.fetched == [EXPECTED_BYTES]


async def test_upload_does_not_report_success_before_the_write_is_readable() -> None:
    """The guarantee the port states, at the adapter that has to keep it."""
    client = _LaggingMinio(reads_before_visible=2)
    storage = _storage_for(client)

    await storage.upload("artifacts/thing.md", EXPECTED_BYTES)

    assert await storage.download("artifacts/thing.md") == EXPECTED_BYTES


@pytest.mark.usefixtures("short_budget")
async def test_upload_fails_when_the_write_never_becomes_readable() -> None:
    """Never return a URI the adapter cannot stand behind."""
    client = _LaggingMinio(reads_before_visible=None)
    storage = _storage_for(client)

    with pytest.raises(UploadError, match="still missing"):
        await storage.upload("artifacts/lost.md", EXPECTED_BYTES)


@pytest.mark.usefixtures("short_budget")
async def test_unconfirmable_upload_leaves_the_event_whole_without_a_uri() -> None:
    """Degrade to event-store-only rather than advertise bytes we cannot serve.

    The content is embedded in the event either way, so the artifact survives;
    what must not survive is a storage_uri pointing at nothing.
    """
    client = _LaggingMinio(reads_before_visible=None)
    storage = _storage_for(client)
    repo = _FetchingRepository(storage)

    await _collect_one(repo, storage)

    assert repo.uris == [None]
    assert repo.failures == []
