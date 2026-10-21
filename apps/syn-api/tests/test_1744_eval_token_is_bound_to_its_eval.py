"""An EVAL token writes to the eval its execution belongs to, and nothing else (#1744).

Two evals are created over HTTP and one run is started in each through the real
execution commands and repository. The token is minted for the owner run with
the eval read off that run's aggregate, which is how provisioning binds it
(`PhaseWorkspace.provision`). Token enforcement, the routes, the scoring
handler and the repositories are all real; only Lane 2 cost reads are faked.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from test_evals_v2_runs_and_scores_over_http import (  # pyright: ignore[reportMissingImports]
    OPUS,
    SHA,
    _create,  # pyright: ignore[reportPrivateUsage]
    _reset_storage,  # pyright: ignore[reportPrivateUsage]  # noqa: F401 - autouse fixture
    _run,  # pyright: ignore[reportPrivateUsage]
    lane2,  # noqa: F401 - fixture
)

from syn_adapters.platform_access import InMemoryPlatformTokenStore, PlatformTokenService
from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver
from syn_shared.platform_access import PlatformScope

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_STARTED = "2026-10-01T00:00:00+00:00"
_SCORE_BODY = {"verdict": "PASS", "score": 1.0, "scorer": "s", "scorer_version": "1"}
# The only two writes an EVAL token may make, as the route table spells them.
_EVAL_WRITES = frozenset(
    {
        ("POST", "/workflows/{workflow_id}/execute"),
        ("POST", "/evals/{eval_id}/runs/{execution_id}/score"),
    }
)


class _World:
    def __init__(
        self,
        app: FastAPI,
        service: PlatformTokenService,
        client: AsyncClient,
        headers: dict[str, str],
        own: str,
        other: str,
    ) -> None:
        self.app = app
        self.service = service
        self.client = client
        self.headers = headers
        self.own = own
        self.other = other


@pytest.fixture
async def world(
    monkeypatch: pytest.MonkeyPatch,
    lane2: object,  # noqa: F811
) -> AsyncIterator[_World]:
    from syn_api import _wiring
    from syn_api.main import create_app

    service = PlatformTokenService(InMemoryPlatformTokenStore(), max_ttl_seconds=3600)
    monkeypatch.setattr(_wiring, "_platform_token_service_singleton", service)
    fake = FakeRevisionResolver(shas={("acme/app", "main"): SHA})
    monkeypatch.setattr("syn_api.routes.evals.get_revision_resolver", lambda: fake)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        own = await _create(client)
        other = await _create(client)
        await _run(lane2, own, "owner-run", "wf-owner", OPUS, "1.00", _STARTED)
        await _run(lane2, other, "other-run", "wf-other", OPUS, "1.00", _STARTED)
        owner = await _wiring.get_workflow_execution_repository().get_by_id("owner-run")
        assert owner is not None
        token = await service.issue("owner-run", PlatformScope.EVAL, owner.eval_membership.eval_id)
        headers = {"x-syn-workspace-ingress": "workspace", "authorization": f"Bearer {token}"}
        yield _World(app, service, client, headers, own, other)


async def _scored(eval_id: str, execution_id: str) -> bool:
    from syn_api._wiring import get_eval_repo

    stored = await get_eval_repo().get_by_id(eval_id)
    assert stored is not None
    return stored.run_score(execution_id) is not None


async def test_own_eval_run_is_scored_and_persisted(world: _World) -> None:
    response = await world.client.post(
        f"/evals/{world.own}/runs/owner-run/score", json=_SCORE_BODY, headers=world.headers
    )
    assert response.status_code == 200, response.text
    assert await _scored(world.own, "owner-run")


async def test_another_evals_run_cannot_be_scored(world: _World) -> None:
    response = await world.client.post(
        f"/evals/{world.other}/runs/other-run/score", json=_SCORE_BODY, headers=world.headers
    )
    assert response.status_code == 403
    assert not await _scored(world.other, "other-run")


async def test_launch_into_own_eval_reaches_the_route(world: _World) -> None:
    response = await world.client.post(
        "/workflows/wf-owner/execute",
        json={"eval_id": world.own, "not_a_field_1744": 1},
        headers=world.headers,
    )
    # The route's own validation answered: ingress let the body through.
    assert response.status_code == 422, response.text
    assert "not_a_field_1744" in response.text


async def test_launch_into_another_eval_is_refused_before_the_route(world: _World) -> None:
    response = await world.client.post(
        "/workflows/wf-owner/execute",
        json={"eval_id": world.other, "not_a_field_1744": 1},
        headers=world.headers,
    )
    assert response.status_code == 403


async def test_an_eval_token_bound_to_no_eval_writes_nothing(world: _World) -> None:
    token = await world.service.issue("owner-run", PlatformScope.EVAL, None)
    headers = {"x-syn-workspace-ingress": "workspace", "authorization": f"Bearer {token}"}
    score = await world.client.post(
        f"/evals/{world.own}/runs/owner-run/score", json=_SCORE_BODY, headers=headers
    )
    launch = await world.client.post(
        "/workflows/wf-owner/execute", json={"eval_id": world.own}, headers=headers
    )
    assert (score.status_code, launch.status_code) == (403, 403)
    assert not await _scored(world.own, "owner-run")


async def test_every_non_get_route_but_the_two_own_eval_writes_is_refused(
    world: _World,
) -> None:
    """Walk the whole route table, so a route added or widened later is covered too."""
    checked: list[tuple[str, str]] = []
    for route in world.app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods - {"GET", "HEAD"}):
            # Every path parameter named after the OWN eval and run: the most
            # favourable request a token can make to a route it must not reach.
            path = route.path.replace("{eval_id}", world.own).replace("{execution_id}", "owner-run")
            path = re.sub(r"\{[^}]+\}", "target-1744", path)
            response = await world.client.request(
                method, path, json={"eval_id": world.own}, headers=world.headers
            )
            if (method, route.path) in _EVAL_WRITES:
                assert response.status_code != 403, f"{method} {route.path}"
            else:
                assert response.status_code == 403, f"{method} {route.path}"
            checked.append((method, route.path))
    assert set(checked) >= _EVAL_WRITES
    assert len(checked) > len(_EVAL_WRITES)
