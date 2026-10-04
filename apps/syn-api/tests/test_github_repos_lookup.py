"""`GET /github/repos` says whether a missing repo is out of reach or went unseen.

The dashboard's Repos page labels a registered repo ``Not attached`` when the
App's listing does not contain it. That is only true when GitHub answered for
every installation, so the route reports ``lookup`` and the page reads it.

Each scenario here is served by the real route with a GitHub client that
answers, or fails, as described. The responses are recorded into
``fixtures/github_repos_lookup.json``, which the dashboard's Repos page test
serves as ``/github/repos`` and asserts badges against. The committed fixture
must equal what this test regenerates, so the page test cannot drift from the
route. Regenerate after an intended contract change with
``SYN_UPDATE_GITHUB_REPOS_FIXTURE=1 uv run pytest apps/syn-api/tests/test_github_repos_lookup.py``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, JsonValue

from syn_api.routes.github import router
from syn_api.types import GitHubRepoListResponse, GitHubRepoLookup

FIXTURE = Path(__file__).parent / "fixtures" / "github_repos_lookup.json"

_PROJECTION = (
    "syn_domain.contexts.github.slices.get_installation.projection.get_installation_projection"
)


def _raw_repo(github_id: int, full_name: str) -> JsonValue:
    return {
        "id": github_id,
        "name": full_name.split("/")[1],
        "full_name": full_name,
        "private": False,
        "default_branch": "main",
    }


def _installation(installation_id: str, *, synced_minutes_ago: int = 5) -> MagicMock:
    inst = MagicMock()
    inst.installation_id = installation_id
    inst.synced_at = datetime.now(UTC) - timedelta(minutes=synced_minutes_ago)
    return inst


def _get(
    *,
    cached: list[MagicMock],
    repos_by_installation: list[list[JsonValue] | Exception],
    installations_sync: list[JsonValue] | Exception | None = None,
    upserted: list[MagicMock | Exception] | None = None,
) -> JsonValue:
    """Serve one `/github/repos` request against a scripted GitHub client.

    ``upserted`` scripts persisting each synced installation, in order; by
    default every upsert succeeds.
    """
    client = MagicMock()
    client.list_accessible_repos = AsyncMock(side_effect=repos_by_installation)
    if isinstance(installations_sync, Exception):
        client.list_installations = AsyncMock(side_effect=installations_sync)
    else:
        client.list_installations = AsyncMock(return_value=installations_sync or [])
    projection = MagicMock()
    projection.get_all_active = AsyncMock(return_value=cached)
    if upserted is None:
        projection.upsert_from_github_api = AsyncMock(side_effect=lambda _raw: cached[0])
    else:
        projection.upsert_from_github_api = AsyncMock(side_effect=upserted)

    app = FastAPI()
    app.include_router(router)
    with (
        patch("syn_api.routes.github.ensure_connected", new_callable=AsyncMock),
        patch("syn_adapters.github.client.get_github_client", return_value=client),
        patch(_PROJECTION, return_value=projection),
    ):
        response = TestClient(app).get("/github/repos")
    assert response.status_code == 200
    body: JsonValue = response.json()
    return body


def _lookup(body: JsonValue) -> GitHubRepoListResponse:
    return GitHubRepoListResponse.model_validate(body)


class _Fixture(BaseModel):
    """One recorded `/github/repos` body per situation the Repos page must label."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    confirmed_empty: JsonValue
    installation_lookup_failed: JsonValue
    one_installation_failed: JsonValue
    installation_not_persisted: JsonValue


def _generate() -> _Fixture:
    return _Fixture(
        # GitHub answered for the only installation: it reaches nothing.
        confirmed_empty=_get(cached=[_installation("inst-1")], repos_by_installation=[[]]),
        # GitHub failed for the only installation: nothing is known.
        installation_lookup_failed=_get(
            cached=[_installation("inst-1")],
            repos_by_installation=[RuntimeError("GitHub 502")],
        ),
        # One installation answered, the other failed.
        one_installation_failed=_get(
            cached=[_installation("inst-1"), _installation("inst-2")],
            repos_by_installation=[
                [_raw_repo(1, "acme/payments")],
                RuntimeError("GitHub 502"),
            ],
        ),
        # GitHub listed the only installation, but saving it failed, so its
        # repos were never asked for.
        installation_not_persisted=_get(
            cached=[],
            repos_by_installation=[],
            installations_sync=[{"id": 1}],
            upserted=[OSError("projection store unavailable")],
        ),
    )


def _serialized(fixture: _Fixture) -> str:
    return json.dumps(fixture.model_dump(mode="json"), indent=1, sort_keys=True) + "\n"


def test_fixture_is_regenerated_from_the_route() -> None:
    generated = _serialized(_generate())
    if os.environ.get("SYN_UPDATE_GITHUB_REPOS_FIXTURE") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(generated)
    assert FIXTURE.exists(), "run with SYN_UPDATE_GITHUB_REPOS_FIXTURE=1 to create the fixture"
    assert FIXTURE.read_text() == generated, (
        "github repos fixture drifted from the route; "
        "regenerate with SYN_UPDATE_GITHUB_REPOS_FIXTURE=1"
    )


def test_a_failed_installation_lookup_is_not_a_confirmed_empty_one() -> None:
    fixture = _generate()

    confirmed = _lookup(fixture.confirmed_empty)
    failed = _lookup(fixture.installation_lookup_failed)
    assert (confirmed.repos, confirmed.lookup) == ([], GitHubRepoLookup.COMPLETE)
    assert (failed.repos, failed.lookup) == ([], GitHubRepoLookup.UNAVAILABLE)

    partial = _lookup(fixture.one_installation_failed)
    assert [r.full_name for r in partial.repos] == ["acme/payments"]
    assert partial.lookup == GitHubRepoLookup.PARTIAL


def test_installation_sync_failure_with_no_cache_is_unavailable() -> None:
    body = _get(cached=[], repos_by_installation=[], installations_sync=RuntimeError("GitHub 502"))
    assert _lookup(body).lookup == GitHubRepoLookup.UNAVAILABLE


def test_installation_sync_success_with_no_installations_is_complete() -> None:
    body = _get(cached=[], repos_by_installation=[], installations_sync=[])
    assert _lookup(body).lookup == GitHubRepoLookup.COMPLETE


def test_stale_cache_kept_after_sync_failure_is_partial() -> None:
    """The kept list may be missing an installation, so absence proves nothing."""
    body = _get(
        cached=[_installation("inst-1", synced_minutes_ago=90)],
        repos_by_installation=[[_raw_repo(1, "acme/payments")]],
        installations_sync=RuntimeError("GitHub 502"),
    )
    listing = _lookup(body)
    assert [r.full_name for r in listing.repos] == ["acme/payments"]
    assert listing.lookup == GitHubRepoLookup.PARTIAL


@pytest.mark.parametrize("installations", [1, 2])
def test_every_installation_failing_is_unavailable(installations: int) -> None:
    body = _get(
        cached=[_installation(f"inst-{i}") for i in range(installations)],
        repos_by_installation=[RuntimeError("GitHub 502")] * installations,
    )
    assert _lookup(body).lookup == GitHubRepoLookup.UNAVAILABLE


def test_an_installation_that_failed_to_persist_is_not_a_confirmed_absence() -> None:
    assert _lookup(_generate().installation_not_persisted).lookup == GitHubRepoLookup.UNAVAILABLE


def test_one_installation_failing_to_persist_makes_the_lookup_partial() -> None:
    body = _get(
        cached=[],
        repos_by_installation=[[_raw_repo(1, "acme/payments")]],
        installations_sync=[{"id": 1}, {"id": 2}],
        upserted=[_installation("inst-1"), OSError("projection store unavailable")],
    )
    listing = _lookup(body)
    assert [r.full_name for r in listing.repos] == ["acme/payments"]
    assert listing.lookup == GitHubRepoLookup.PARTIAL
