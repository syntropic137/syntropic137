"""An EVAL platform token reaches exactly two writes, enforced by the API (#1744, ADR-072).

Through the real ``create_app()`` stack, as Envoy delivers workspace traffic.
Where a request is let through, the assertion is that the ROUTE answered it -
a 422 naming a field only the request body carried - because a request let
past the enforcer with its body consumed and not replayed would also escape a
403, and would reach the route empty.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.platform_access import (
    MAX_EVAL_BODY_BYTES,
    InMemoryPlatformTokenStore,
    PlatformTokenService,
)
from syn_shared.platform_access import PlatformScope

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit

_INGRESS = {"x-syn-workspace-ingress": "workspace"}
_EXECUTE = "/workflows/wf-1/execute"
_SCORE = "/evals/ev-1/runs/exec-1/score"


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def service(clock: _Clock) -> PlatformTokenService:
    return PlatformTokenService(InMemoryPlatformTokenStore(), max_ttl_seconds=3600, now=clock)


@pytest.fixture
async def client(
    service: PlatformTokenService, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    from syn_api import _wiring
    from syn_api.main import create_app

    monkeypatch.setattr(_wiring, "_platform_token_service_singleton", service)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


async def _bearer(service: PlatformTokenService, scope: PlatformScope) -> dict[str, str]:
    token = await service.issue("exec-1744", scope)
    return {**_INGRESS, "authorization": f"Bearer {token}", "content-type": "application/json"}


def _route_rejected_only(response_text: str, field: str) -> bool:
    """The route's own validation answered, about a field carried in the body."""
    return any(field in error["loc"] for error in json.loads(response_text)["detail"])


class TestEvalTokenReachesItsTwoWrites:
    async def test_execute_naming_an_eval_reaches_the_route_with_its_body(
        self, client: AsyncClient, service: PlatformTokenService
    ) -> None:
        body = {"eval_id": "ev-1", "not_a_field_1744": 1}
        response = await client.post(
            _EXECUTE, json=body, headers=await _bearer(service, PlatformScope.EVAL)
        )
        assert response.status_code == 422
        assert _route_rejected_only(response.text, "not_a_field_1744")

    async def test_score_reaches_the_route_with_its_body(
        self, client: AsyncClient, service: PlatformTokenService
    ) -> None:
        body = {"verdict": "pass", "scorer": "s", "scorer_version": "1", "not_a_field_1744": 1}
        response = await client.post(
            _SCORE, json=body, headers=await _bearer(service, PlatformScope.EVAL)
        )
        assert response.status_code == 422
        assert _route_rejected_only(response.text, "not_a_field_1744")

    async def test_eval_token_still_reads(
        self, client: AsyncClient, service: PlatformTokenService
    ) -> None:
        response = await client.get("/health", headers=await _bearer(service, PlatformScope.EVAL))
        assert response.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        b"{}",  # would fall back to the workflow's default eval, or none
        b'{"inputs": {}}',
        b'{"eval_id": null}',
        b'{"eval_id": ""}',
        b'{"eval_id": "  "}',
        b'{"eval_id": 7}',
        b'{"eval_id": "ev-1", "no_eval": true}',
        b'{"eval_id": "ev-1", "no_eval": "true"}',  # the route reads this as true too
        b'{"no_eval": false, "eval_id": "ev-1", "eval_id": null}',  # last key wins, as in the route
        b'["eval_id", "ev-1"]',
        b"eval_id=ev-1",
        b"",
    ],
)
async def test_eval_token_cannot_launch_outside_a_named_eval(
    client: AsyncClient, service: PlatformTokenService, body: bytes
) -> None:
    response = await client.post(
        _EXECUTE, content=body, headers=await _bearer(service, PlatformScope.EVAL)
    )
    assert response.status_code == 403


async def test_an_oversized_execute_body_is_refused_unread(
    client: AsyncClient, service: PlatformTokenService
) -> None:
    padding = "x" * MAX_EVAL_BODY_BYTES
    body = json.dumps({"eval_id": "ev-1", "inputs": {"pad": padding}}).encode()
    response = await client.post(
        _EXECUTE, content=body, headers=await _bearer(service, PlatformScope.EVAL)
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/workflows"),
        ("POST", "/workflows/wf-1/execute/extra"),
        ("POST", "/workflows/execute"),
        ("PUT", _EXECUTE),
        ("POST", "/evals"),
        ("POST", "/evals/ev-1/runs/exec-1/score/extra"),
        ("PUT", _SCORE),
        ("DELETE", _SCORE),
        ("POST", "/evals/ev-1/runs/exec-1"),
        ("PUT", "/executions/exec-1/eval"),
        ("POST", "/executions/exec-1/cancel"),
        ("GET", "/workflows"),
        ("GET", "/triggers"),
        ("GET", "/costs"),
    ],
)
async def test_eval_token_is_refused_everything_else(
    client: AsyncClient, service: PlatformTokenService, method: str, path: str
) -> None:
    response = await client.request(
        method,
        path,
        content=b'{"eval_id": "ev-1"}',
        headers=await _bearer(service, PlatformScope.EVAL),
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    ("path", "body"),
    [(_EXECUTE, b'{"eval_id": "ev-1"}'), (_SCORE, b'{"verdict": "pass"}')],
)
async def test_read_token_reaches_neither_eval_write(
    client: AsyncClient, service: PlatformTokenService, path: str, body: bytes
) -> None:
    response = await client.post(
        path, content=body, headers=await _bearer(service, PlatformScope.READ)
    )
    assert response.status_code == 403


async def test_an_expired_eval_token_is_refused(
    client: AsyncClient, service: PlatformTokenService, clock: _Clock
) -> None:
    headers = await _bearer(service, PlatformScope.EVAL)
    clock.now += timedelta(seconds=3601)
    response = await client.post(_SCORE, content=b"{}", headers=headers)
    assert response.status_code == 401
