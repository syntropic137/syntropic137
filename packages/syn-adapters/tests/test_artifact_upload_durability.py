"""An artifact's metadata event must not outrun its bytes (#700).

`ArtifactCreatedEvent` carries a `storage_uri`. A consumer that reacts to the
event and fetches that URI straight away was getting a 404 or a short object,
because `put_object` returning only means the backend accepted the write.

These tests drive the real chain - `ArtifactCollector` -> `MinioArtifactStorage`
-> `MinioStorage` - against a client that reproduces the window, and assert
from the position of that consumer rather than from either end of it.

The guarantee under test is READABILITY: a read issued the moment the event
exists returns the bytes the event describes. Durability is a property of how
the backend is deployed and cannot be established from the client, so nothing
here claims it - see `await_readable_content`.
"""

from __future__ import annotations

import hashlib
from itertools import repeat
from typing import TYPE_CHECKING, NamedTuple

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
    from collections.abc import Iterable, Iterator

pytestmark = pytest.mark.unit

BUCKET = "syn-artifacts"
CONTENT = "# Deliverable\nthe bytes a consumer will ask for"
EXPECTED_BYTES = CONTENT.encode("utf-8")
EXPECTED_SHA256 = hashlib.sha256(EXPECTED_BYTES).hexdigest()

#: A PREVIOUS value at the same key, the same length as the new one. Same
#: length is the whole point: it is what a size comparison cannot tell apart.
STALE_BYTES = b"S" * len(EXPECTED_BYTES)

#: Long enough that a checker which consumes only ONE read leaves the rest of
#: the divergence standing for the consumer behind it. A checker that actually
#: reads content keeps reading until it matches, and so absorbs all of it.
DIVERGENT_READS = 3


class _NoSuchKey(Exception):
    """What an S3-compatible backend answers for an object it cannot serve."""

    def __init__(self, key: str) -> None:
        super().__init__(f"NoSuchKey: {key} does not exist")


class _Visibility(NamedTuple):
    """One read's worth of backend state, as HEAD and as GET see it.

    They are separate fields because on a real backend they disagree: HEAD is
    answered from a metadata index, GET has to find the bytes. Every way the
    old size-only check was wrong is a `_Visibility` whose `head` is honest and
    whose `get` is not.
    """

    head: int | None
    """Size a `stat_object` reports, or None for NoSuchKey."""

    get: bytes | None
    """Bytes a `get_object` serves, or None for NoSuchKey."""


def _nothing_yet() -> _Visibility:
    """The write has not landed anywhere a reader can see it."""
    return _Visibility(head=None, get=None)


def _short(payload: bytes) -> _Visibility:
    """Consistently truncated - HEAD and GET agree, and both are short."""
    return _Visibility(head=len(payload), get=payload)


def _head_lies(get: bytes | None) -> _Visibility:
    """HEAD reports the full written size; the GET behind it does not deliver.

    This is the shape a size comparison cannot see, whether the bytes are
    absent, truncated, or simply the previous ones.
    """
    return _Visibility(head=len(EXPECTED_BYTES), get=get)


class _PutResult:
    def __init__(self, etag: str) -> None:
        self.etag = etag


class _Stat:
    def __init__(self, size: int) -> None:
        self.size = size


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
    """A MinIO client whose accepted write is not yet what a read returns.

    `window` scripts the reads that follow the put: each entry is one read
    attempt's view of the key, and HEAD and GET are served from it
    independently. When the script runs out, reads see what was written.
    An endless script (`repeat(...)`) is a write that never becomes readable.

    Counting READS rather than seconds is what makes this an ordering test
    instead of a race against a clock: whoever reads first is the one that
    meets the gap, so a caller that publishes before confirming - or confirms
    without reading - is the caller that gets caught.
    """

    def __init__(self, window: Iterable[_Visibility] = ()) -> None:
        self._window = iter(window)
        self._objects: dict[str, bytes] = {}
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
        return _PutResult(etag="etag-for-" + key)

    def _next_view(self, key: str) -> _Visibility:
        """What this read sees, consuming one step of the window."""
        self.reads.append(key)
        written = self._objects.get(key)
        settled = _Visibility(
            head=None if written is None else len(written),
            get=written,
        )
        return next(self._window, settled)

    def stat_object(self, bucket_name: str, key: str) -> _Stat:
        size = self._next_view(key).head
        if size is None:
            raise _NoSuchKey(key)
        return _Stat(size=size)

    def get_object(self, bucket_name: str, key: str) -> _Response:
        payload = self._next_view(key).get
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
        self.events: list[object] = []
        self.fetched: list[bytes] = []
        self.failures: list[str] = []
        self.uris: list[str | None] = []

    async def save(self, aggregate: object) -> None:
        for envelope in aggregate.get_uncommitted_events():  # type: ignore[attr-defined]
            self.events.append(envelope.event)
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
    client = _LaggingMinio(window=[_nothing_yet()])
    storage = _storage_for(client)
    repo = _FetchingRepository(storage)

    await _collect_one(repo, storage)

    assert repo.uris == ["s3://syn-artifacts/artifacts/wf-1/exec-1/artifact-700.md"]
    assert repo.failures == []
    assert repo.fetched == [EXPECTED_BYTES]


async def test_consumer_is_not_handed_a_short_object() -> None:
    """A truncated read is the same broken promise as a missing one."""
    client = _LaggingMinio(window=[_short(EXPECTED_BYTES[:1])])
    storage = _storage_for(client)
    repo = _FetchingRepository(storage)

    await _collect_one(repo, storage)

    assert repo.failures == []
    assert repo.fetched == [EXPECTED_BYTES]


@pytest.mark.parametrize(
    ("what_the_get_serves", "label"),
    [
        (None, "the GET 404s"),
        (EXPECTED_BYTES[:5], "the GET is truncated"),
    ],
)
async def test_a_head_of_the_right_size_does_not_make_the_bytes_readable(
    what_the_get_serves: bytes | None,
    label: str,
) -> None:
    """HEAD reporting the written length is not evidence a reader gets it.

    A confirmation built on `stat_object` passes here on its first call and
    hands the rest of the window to the consumer, which is exactly the consumer
    #700 is about. Only a confirmation that reads the bytes waits this out.
    """
    client = _LaggingMinio(window=[_head_lies(what_the_get_serves)] * DIVERGENT_READS)
    storage = _storage_for(client)
    repo = _FetchingRepository(storage)

    await _collect_one(repo, storage)

    assert repo.failures == [], f"{label}, and the consumer was handed the URI anyway"
    assert repo.fetched == [EXPECTED_BYTES]


async def test_a_stale_object_of_the_same_size_is_not_mistaken_for_the_new_one() -> None:
    """The key already held something the same length, and it is still served.

    Nothing 404s and nothing is short, so every signal short of the content
    itself says the write is visible. The consumer gets the PREVIOUS artifact's
    bytes under the new artifact's URI - silent, and wrong in the worst way,
    because it reads as success at every layer.
    """
    assert len(STALE_BYTES) == len(EXPECTED_BYTES), "the stale object must be the same size"
    assert STALE_BYTES != EXPECTED_BYTES

    client = _LaggingMinio(window=[_head_lies(STALE_BYTES)] * DIVERGENT_READS)
    storage = _storage_for(client)
    repo = _FetchingRepository(storage)

    await _collect_one(repo, storage)

    assert repo.failures == []
    assert repo.fetched == [EXPECTED_BYTES]


async def test_upload_does_not_report_success_before_the_write_is_readable() -> None:
    """The guarantee the port states, at the adapter that has to keep it."""
    client = _LaggingMinio(window=[_nothing_yet(), _nothing_yet()])
    storage = _storage_for(client)

    await storage.upload("artifacts/thing.md", EXPECTED_BYTES)

    assert await storage.download("artifacts/thing.md") == EXPECTED_BYTES


@pytest.mark.usefixtures("short_budget")
async def test_upload_fails_when_the_write_never_becomes_readable() -> None:
    """Never return a URI the adapter cannot stand behind."""
    client = _LaggingMinio(window=repeat(_nothing_yet()))
    storage = _storage_for(client)

    with pytest.raises(UploadError, match="a read still returns missing"):
        await storage.upload("artifacts/lost.md", EXPECTED_BYTES)


@pytest.mark.usefixtures("short_budget")
async def test_upload_fails_when_the_key_only_ever_serves_the_previous_object() -> None:
    """A permanently stale key fails the upload rather than publishing its URI."""
    client = _LaggingMinio(window=repeat(_head_lies(STALE_BYTES)))
    storage = _storage_for(client)

    with pytest.raises(UploadError, match="a read still returns .* bytes hashing sha256:"):
        await storage.upload("artifacts/stale.md", EXPECTED_BYTES)


@pytest.mark.usefixtures("short_budget")
async def test_unconfirmable_upload_leaves_the_event_whole_without_a_uri() -> None:
    """Degrade to event-store-only rather than advertise bytes we cannot serve.

    The content is embedded in the event either way, so the artifact survives;
    what must not survive is a storage_uri pointing at nothing. Assert the
    surviving half, not just the absent one - "no URI" is only defensible
    because the bytes and their hash are still on the event.
    """
    client = _LaggingMinio(window=repeat(_nothing_yet()))
    storage = _storage_for(client)
    repo = _FetchingRepository(storage)

    await _collect_one(repo, storage)

    assert repo.uris == [None]
    assert repo.failures == []
    (saved,) = repo.events
    assert saved.content == CONTENT  # type: ignore[attr-defined]
    assert saved.content_hash == EXPECTED_SHA256  # type: ignore[attr-defined]
    assert saved.size_bytes == len(EXPECTED_BYTES)  # type: ignore[attr-defined]


async def test_a_caller_bug_is_not_degraded_into_a_missing_uri() -> None:
    """Only a storage failure downgrades the artifact; our own bugs surface.

    The old `except Exception` could not tell these apart, so a broken call
    into the port would have logged a storage warning and written every
    artifact without a URI, indefinitely and silently.
    """

    class _BrokenPort:
        async def upload(self, *args: object, **kwargs: object) -> object:
            raise TypeError("upload() got an unexpected keyword argument 'phase_id'")

    repo = _FetchingRepository(_storage_for(_LaggingMinio()))
    collector = ArtifactCollector(
        repository=repo,
        content_storage=_BrokenPort(),
        query_service=None,
    )

    with pytest.raises(TypeError, match="unexpected keyword argument"):
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

    assert repo.events == [], "nothing should have been saved"
