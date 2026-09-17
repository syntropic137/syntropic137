"""`GET /artifacts/{id}` must answer with who produced the artifact (#1284).

The value exists in the event and in the read model; this is about the last two
hops, which are the ones that can drop it silently. `GET /artifacts/{id}` does
not answer with `ArtifactDetail` - it answers with `ArtifactResponse`, a second
Pydantic model built field by field from the first. A field added to one and not
the other, or to both and not to the construction between them, is absent on the
wire while every domain test still passes.

The artifact here is created through the DOMAIN path rather than `POST
/artifacts`, because the write API deliberately does not accept these two
fields: a client that could assert "gpt-5 produced this" would be able to forge
exactly the provenance the field exists to establish. Only the platform, which
launched the harness and read its stream, may state it.
"""

import os

import pytest

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

PROVIDER = "codex"
#: A claude model name on a codex phase: a pair nothing in this system
#: configures, so it cannot have been reconstructed from config on the way out.
ANNOUNCED_MODEL = "claude-sonnet-4-5-20250929"


@pytest.fixture(autouse=True)
def _reset_storage():
    """Reset in-memory storage and projections between tests."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


async def _store_artifact(
    artifact_id: str,
    *,
    agent_provider: str | None,
    agent_model: str | None,
) -> None:
    """Create an artifact the way a phase does, and index it for the read path."""
    from syn_api._wiring import (
        ensure_connected,
        get_artifact_repo,
        sync_published_events_to_projections,
    )
    from syn_domain.contexts.artifacts import (
        ArtifactAggregate,
        ArtifactType,
        CreateArtifactCommand,
    )

    await ensure_connected()
    aggregate = ArtifactAggregate()
    aggregate.create_artifact(
        CreateArtifactCommand(
            aggregate_id=artifact_id,
            workflow_id="wf-1284",
            phase_id="verify",
            artifact_type=ArtifactType.MARKDOWN,
            content="# Review\n\nthe verdict",
            title="Verify: artifacts/output/deliverable.md",
            agent_provider=agent_provider,
            agent_model=agent_model,
        )
    )
    await get_artifact_repo().save(aggregate)
    await sync_published_events_to_projections()


async def test_the_detail_endpoint_names_the_harness_and_the_model():
    """The whole point of the issue: a later phase asks the API who produced
    its inputs and gets an answer instead of "could not determine"."""
    from syn_api.routes.artifacts import get_artifact_endpoint

    await _store_artifact("art-1284-a", agent_provider=PROVIDER, agent_model=ANNOUNCED_MODEL)

    response = await get_artifact_endpoint("art-1284-a")

    assert response.agent_provider == PROVIDER
    assert response.agent_model == ANNOUNCED_MODEL


async def test_a_harness_that_announced_no_model_is_reported_as_such():
    """Every codex phase today. The provider still proves which harness ran;
    the model comes back null rather than as the configured one, so a caller
    renders "not reported" instead of a claim nobody made."""
    from syn_api.routes.artifacts import get_artifact_endpoint

    await _store_artifact("art-1284-b", agent_provider=PROVIDER, agent_model=None)

    response = await get_artifact_endpoint("art-1284-b")

    assert response.agent_provider == PROVIDER
    assert response.agent_model is None


async def test_the_internal_detail_model_carries_it_too():
    """`get_artifact` is what every other consumer of the detail shape reads;
    the endpoint above can only report what this hop hands it."""
    from syn_api.routes.artifacts import get_artifact
    from syn_api.types import Ok

    await _store_artifact("art-1284-c", agent_provider="claude", agent_model=ANNOUNCED_MODEL)

    result = await get_artifact("art-1284-c", include_content=True)

    assert isinstance(result, Ok)
    assert result.value.agent_provider == "claude"
    assert result.value.agent_model == ANNOUNCED_MODEL


async def test_the_list_surface_names_them_without_a_second_request():
    """A reviewer asks "which models produced this execution's phases" of the
    LIST. Needing a detail call per row to answer it is the same gap one
    request further out."""
    from syn_api.routes.artifacts import list_artifacts
    from syn_api.types import Ok

    await _store_artifact("art-1284-d", agent_provider=PROVIDER, agent_model=ANNOUNCED_MODEL)

    result = await list_artifacts(workflow_id="wf-1284")

    assert isinstance(result, Ok)
    assert [(r.agent_provider, r.agent_model) for r in result.value.rows] == [
        (PROVIDER, ANNOUNCED_MODEL)
    ]


async def test_an_artifact_created_through_the_write_api_reports_nothing():
    """No harness ran it, so there is nothing to report - and the write API
    offers no way to claim otherwise, which is deliberate: a forgeable
    provenance field is worse than an absent one."""
    from syn_api.routes.artifacts import create_artifact, get_artifact_endpoint
    from syn_api.types import Ok

    created = await create_artifact(
        workflow_id="wf-1284",
        artifact_type="other",
        title="Hand-made",
        content="written by a person",
    )
    assert isinstance(created, Ok)

    response = await get_artifact_endpoint(created.value)

    assert response.agent_provider is None
    assert response.agent_model is None


async def test_the_list_endpoint_names_them_on_the_wire():
    """The list has the same two hops the detail has, and the second one -
    rebuilding every row as a response model field by field - is where the
    field was in fact dropped: `list_artifacts` restated ten fields and not
    these two, so `GET /artifacts` answered null for an artifact whose
    `GET /artifacts/{id}` answered correctly, in the same process.
    """
    from syn_api.routes.artifacts import list_artifacts_endpoint

    await _store_artifact("art-1284-e", agent_provider=PROVIDER, agent_model=ANNOUNCED_MODEL)

    response = await list_artifacts_endpoint(
        workflow_id="wf-1284",
        phase_id=None,
        session_id=None,
        artifact_type=None,
        created_after=None,
        created_before=None,
        q=None,
        page=1,
        page_size=50,
        limit=None,
    )

    assert [(r.id, r.agent_provider, r.agent_model) for r in response.artifacts] == [
        ("art-1284-e", PROVIDER, ANNOUNCED_MODEL)
    ]
