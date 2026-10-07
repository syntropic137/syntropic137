"""A workspace's platform token is enforced by the API itself (PC-127, ADR-072).

Every request here goes through the real ``create_app()`` stack over HTTP, as
the Envoy sidecar delivers it: with ``x-syn-workspace-ingress`` set. A scope
check that is right in ``PlatformTokenService`` but never installed in the app,
or installed behind a router, passes every test of the service and fails these.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.in_memory import InMemoryAdapterError
from syn_adapters.platform_access import InMemoryPlatformTokenStore, PlatformTokenService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.unit

_INGRESS = {"x-syn-workspace-ingress": "workspace"}


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


async def _client(service: PlatformTokenService, monkeypatch: pytest.MonkeyPatch) -> AsyncClient:
    from syn_api import _wiring
    from syn_api.main import create_app

    monkeypatch.setattr(_wiring, "_platform_token_service_singleton", service)
    return AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t")


@pytest.fixture
def service(clock: _Clock) -> PlatformTokenService:
    return PlatformTokenService(InMemoryPlatformTokenStore(), max_ttl_seconds=3600, now=clock)


@pytest.fixture
async def client(
    service: PlatformTokenService, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    async with await _client(service, monkeypatch) as c:
        yield c


def _bearer(token: str) -> dict[str, str]:
    return {**_INGRESS, "authorization": f"Bearer {token}"}


async def test_read_token_reaches_a_read_route(
    client: AsyncClient, service: PlatformTokenService
) -> None:
    token = await service.issue("exec-pc127")
    response = await client.get("/health", headers=_bearer(token))
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/workflows/wf-1/execute"),
        ("POST", "/evals"),
        ("PUT", "/executions/exec-1/eval"),
        ("DELETE", "/executions/exec-1/eval"),
        ("POST", "/executions/exec-1/cancel"),
        ("GET", "/workflows"),
        ("GET", "/triggers"),
        ("GET", "/github/installations"),
        ("GET", "/organizations"),
        ("GET", "/costs"),
    ],
)
async def test_read_token_cannot_write_or_read_outside_its_scope(
    client: AsyncClient, service: PlatformTokenService, method: str, path: str
) -> None:
    token = await service.issue("exec-pc127")
    response = await client.request(method, path, headers=_bearer(token))
    assert response.status_code == 403
    assert token not in response.text


async def test_ingress_without_a_token_is_refused(client: AsyncClient) -> None:
    response = await client.get("/executions", headers=_INGRESS)
    assert response.status_code == 401


async def test_a_forged_token_is_refused(client: AsyncClient) -> None:
    response = await client.get("/executions", headers=_bearer("synpt_made-up"))
    assert response.status_code == 401


async def test_an_expired_token_is_refused(
    client: AsyncClient, service: PlatformTokenService, clock: _Clock
) -> None:
    token = await service.issue("exec-pc127")
    clock.now += timedelta(seconds=3601)
    response = await client.get("/health", headers=_bearer(token))
    assert response.status_code == 401


async def test_a_revoked_token_is_refused(
    client: AsyncClient, service: PlatformTokenService
) -> None:
    token = await service.issue("exec-pc127")
    await service.revoke(token)
    response = await client.get("/health", headers=_bearer(token))
    assert response.status_code == 401


async def test_setting_off_refuses_every_workspace_request_and_issues_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SYN_PLATFORM_ACCESS_ENABLED", raising=False)
    from syn_api import _wiring

    monkeypatch.setattr(_wiring, "_platform_token_service_singleton", None)
    disabled = _wiring.get_platform_token_service()
    assert not disabled.enabled
    with pytest.raises(PermissionError):
        await disabled.issue("exec-pc127")

    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        assert (await c.get("/health", headers=_bearer("synpt_anything"))).status_code == 403
        # Internal traffic, which never carries the ingress header, is untouched.
        assert (await c.get("/health")).status_code == 200


async def test_setting_on_wires_a_store_that_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYN_PLATFORM_ACCESS_ENABLED", "true")
    from syn_api import _wiring

    monkeypatch.setattr(_wiring, "_platform_token_service_singleton", None)
    enabled = _wiring.get_platform_token_service()
    assert enabled.enabled
    assert (await enabled.issue("exec-pc127")).startswith("synpt_")
    monkeypatch.setattr(_wiring, "_platform_token_service_singleton", None)


def test_in_memory_store_refuses_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    from syn_shared.settings.config import reset_settings

    reset_settings()
    try:
        with pytest.raises(InMemoryAdapterError):
            InMemoryPlatformTokenStore()
    finally:
        monkeypatch.undo()
        reset_settings()
