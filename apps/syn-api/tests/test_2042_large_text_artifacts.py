"""A text artifact too large to embed survives collection, the API and the handoff (#2042).

WHAT WAS BROKEN. `ArtifactAggregate` embedded TEXT content in
`ArtifactCreatedEvent.content` at any size. One CI log made a 4,533,005-byte
append, the event store's gRPC limit (4 MiB) refused it with OUT_OF_RANGE, and
a phase that had already completed failed. Uploading the text to object storage
first did not help: the event carried it as well.

So text over `MAX_INLINE_TEXT_BYTES` is stored like binary (#990): `content`
is "" in the event and the text is at `storage_uri` only. Each test reads it
back through a CONSUMER - the API and the next phase's workspace - because an
event that is small only because it lost the text would pass a test of the
event alone.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from syn_adapters.projection_stores.memory_store import InMemoryProjectionStore
from syn_adapters.storage.artifact_storage.memory import InMemoryArtifactStorage
from syn_api.routes.artifacts import create_artifact, get_artifact_content_endpoint
from syn_api.types import Ok
from syn_domain.contexts.artifacts import (
    UNREPORTED_AGENT,
    ArtifactType,
    ContentType,
    CreateArtifactCommand,
)
from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
    MAX_INLINE_TEXT_BYTES,
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
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

pytestmark = pytest.mark.unit

#: The event store's gRPC message limit, which one append must stay under.
GRPC_LIMIT = 4 * 1024 * 1024

#: A CI log shaped like the one in #2042: quotes and ANSI colour codes, which
#: JSON escapes to several bytes each. About 3.9 MB, under the gRPC limit as
#: text and over it once embedded in an event.
CI_LOG = ('FAILED test_x - AssertionError: "expected" \x1b[31mred\x1b[0m\n' * 70_000).encode()
LOG_PATH = "artifacts/output/ci.log"
SMALL = b"# Findings\n\nshort enough to stay inline, \x1b[1mbold\x1b[0m.\n"
SMALL_PATH = "artifacts/output/findings.md"


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


@dataclass(frozen=True)
class _World:
    storage: InMemoryArtifactStorage
    projection: ArtifactListProjection
    events: dict[str, ArtifactCreatedEvent]  # source_path -> event
    collector: ArtifactCollector


async def _collect(
    collected: Sequence[tuple[str, bytes]] = ((SMALL_PATH, SMALL), (LOG_PATH, CI_LOG)),
) -> _World:
    """Run the real collector and project what it emitted, as the subscription does.

    The collector marks the first file collected as the primary deliverable.
    """
    storage = InMemoryArtifactStorage()
    repo = _Repo()
    collector = ArtifactCollector(repo, storage, None)  # type: ignore[arg-type]
    await collector.collect_from_workspace(
        workspace=_Workspace(collected=list(collected)),  # type: ignore[arg-type]
        workflow_id="wf-2042",
        phase_id="verify",
        execution_id="exec-2042",
        session_id="s-2042",
        phase_name="Verify",
        output_artifact_types=("markdown",),
        agent=UNREPORTED_AGENT,
    )
    projection = ArtifactListProjection(InMemoryProjectionStore())
    events: dict[str, ArtifactCreatedEvent] = {}
    for aggregate in repo.saved:
        for envelope in aggregate.get_uncommitted_events():
            event = envelope.event
            assert isinstance(event, ArtifactCreatedEvent)
            await projection.on_artifact_created(event.model_dump())
            assert event.source_path is not None
            events[event.source_path] = event
    return _World(storage=storage, projection=projection, events=events, collector=collector)


def _wire_bytes(event: ArtifactCreatedEvent) -> int:
    """The event's size as JSON, the form the store's append carries."""
    return len(json.dumps(event.model_dump(mode="json")).encode("utf-8"))


@pytest.fixture
def api_wired_to() -> Iterator[list[_World]]:
    holder: list[_World] = []

    def mgr() -> object:
        return type("Mgr", (), {"artifact_list": holder[0].projection, "store": None})()

    async def storage() -> InMemoryArtifactStorage:
        return holder[0].storage

    with (
        patch("syn_api.routes.artifacts.ensure_connected", new=AsyncMock()),
        patch("syn_api.routes.artifacts.get_projection_mgr", side_effect=mgr),
        patch(
            "syn_api.prefix_resolver.resolve_prefix_or_keep",
            new=AsyncMock(side_effect=lambda *a: a[2]),
        ),
        patch(
            "syn_adapters.storage.artifact_storage.get_artifact_storage",
            side_effect=storage,
        ),
    ):
        yield holder


class TestTheEventFitsTheStore:
    def test_the_fixture_is_the_failure_it_stands_for(self) -> None:
        """Under the limit as text, over it as JSON: what #2042 hit."""
        assert len(CI_LOG) < GRPC_LIMIT
        assert len(json.dumps(CI_LOG.decode())) > GRPC_LIMIT

    @pytest.mark.asyncio
    async def test_large_text_event_is_small_and_still_describes_the_file(self) -> None:
        world = await _collect()
        event = world.events[LOG_PATH]
        assert _wire_bytes(event) < MAX_INLINE_TEXT_BYTES
        assert event.content == ""
        assert event.storage_uri is not None
        assert event.content_hash == _sha(CI_LOG)
        assert event.size_bytes == len(CI_LOG)

    @pytest.mark.asyncio
    async def test_small_text_is_inline_as_before(self) -> None:
        world = await _collect()
        event = world.events[SMALL_PATH]
        assert event.content == SMALL.decode()
        assert event.content_hash == _sha(SMALL)

    def test_large_text_without_storage_is_refused_not_appended(self) -> None:
        command = CreateArtifactCommand(
            aggregate_id="a-2042",
            workflow_id="wf",
            phase_id="p",
            artifact_type=ArtifactType.TEXT,
            content_type=ContentType.TEXT_PLAIN,
            content="x" * (MAX_INLINE_TEXT_BYTES + 1),
        )
        with pytest.raises(ValueError, match="must be in object storage"):
            ArtifactAggregate().create_artifact(command)

    def test_text_at_the_threshold_stays_inline(self) -> None:
        aggregate = ArtifactAggregate()
        aggregate.create_artifact(
            CreateArtifactCommand(
                aggregate_id="a-edge",
                workflow_id="wf",
                phase_id="p",
                artifact_type=ArtifactType.TEXT,
                content_type=ContentType.TEXT_PLAIN,
                content="x" * MAX_INLINE_TEXT_BYTES,
            )
        )
        assert len(aggregate.content) == MAX_INLINE_TEXT_BYTES


class TestEveryReaderGetsTheWholeText:
    @pytest.mark.asyncio
    async def test_content_route_returns_the_full_text(self, api_wired_to: list[_World]) -> None:
        world = await _collect()
        api_wired_to.append(world)
        response = await get_artifact_content_endpoint(world.events[LOG_PATH].artifact_id)
        assert response.content is not None
        assert _sha(response.content.encode()) == _sha(CI_LOG)

    @pytest.mark.asyncio
    async def test_restart_path_hands_the_next_phase_the_full_text(self) -> None:
        """After a restart the files come from the read model, which holds no text."""
        world = await _collect()
        query = ArtifactQueryService(world.projection, content_storage=world.storage)
        files = await query.get_files_for_phase_injection("exec-2042", ["verify"])
        consumer = _Workspace(collected=[])
        await world.collector.inject_from_previous_phases_explicit(
            consumer,  # type: ignore[arg-type]
            completed_phase_ids=["verify"],
            phase_outputs={},
            phase_files=files,
        )
        injected = dict(consumer.injected)
        assert _sha(injected["artifacts/input/verify/ci.log"]) == _sha(CI_LOG)
        assert injected["artifacts/input/verify/findings.md"] == SMALL

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "collected",
        [
            pytest.param([(LOG_PATH, CI_LOG)], id="sole-large"),
            pytest.param(
                [(LOG_PATH, CI_LOG), ("artifacts/output/notes.log", SMALL)],
                id="large-primary-small-second",
            ),
        ],
    )
    async def test_prompt_substitution_gets_the_full_text_of_a_large_primary(
        self, collected: list[tuple[str, bytes]]
    ) -> None:
        world = await _collect(collected)
        assert world.events[LOG_PATH].is_primary_deliverable
        assert world.events[LOG_PATH].content == ""
        query = ArtifactQueryService(world.projection, content_storage=world.storage)
        outputs = await query.get_for_phase_injection("exec-2042", ["verify"])
        assert list(outputs) == ["verify"]
        assert _sha(outputs["verify"].encode()) == _sha(CI_LOG)


class TestTheCreateRouteStoresLargeText:
    """`POST /artifacts` is a writer too: it must upload large text, not refuse it.

    Before, the route built the command with no `storage_uri`, so the aggregate
    refused any text over `MAX_INLINE_TEXT_BYTES` that main accepted (verifier
    finding on #2306: 524,289 bytes -> 400).
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("text", "inline"),
        [
            pytest.param("x" * (MAX_INLINE_TEXT_BYTES + 1), False, id="one-byte-over"),
            pytest.param(CI_LOG.decode(), False, id="ci-log"),
            pytest.param(SMALL.decode(), True, id="small-stays-inline"),
        ],
    )
    async def test_created_text_round_trips_through_the_content_route(
        self, api_wired_to: list[_World], text: str, inline: bool
    ) -> None:
        world = await _collect(((SMALL_PATH, SMALL),))  # storage + read model to write into
        api_wired_to.append(world)
        repo = _Repo()
        with (
            patch("syn_api.routes.artifacts.get_artifact_repo", return_value=repo),
            patch("syn_api.routes.artifacts.sync_published_events_to_projections", new=AsyncMock()),
        ):
            result = await create_artifact("wf-2042", "other", "log", text, phase_id="api")
        assert isinstance(result, Ok), result
        (aggregate,) = repo.saved
        (envelope,) = aggregate.get_uncommitted_events()
        event = envelope.event
        assert isinstance(event, ArtifactCreatedEvent)
        assert _wire_bytes(event) < GRPC_LIMIT
        assert (event.content == text) is inline
        assert event.content_hash == _sha(text.encode())
        await world.projection.on_artifact_created(event.model_dump())
        response = await get_artifact_content_endpoint(event.artifact_id)
        assert response.content is not None
        assert _sha(response.content.encode()) == _sha(text.encode())
