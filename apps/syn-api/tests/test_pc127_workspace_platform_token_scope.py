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
        ("GET", "/executions/../workflows"),
        ("GET", "/executions/./../triggers"),
        ("GET", "//workflows"),
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


@pytest.mark.parametrize(
    "path", ["/executions/../workflows", "/executions/./x", "/executions//x", "//executions"]
)
async def test_dot_and_empty_segments_are_refused_as_the_api_receives_them(
    service: PlatformTokenService, path: str
) -> None:
    # Called directly: an HTTP client may normalize these before sending, and
    # Envoy (no normalize_path) forwards them as written.
    token = await service.issue("exec-pc127")
    denial = await service.authorize(f"Bearer {token}", "GET", path)
    assert denial is not None
    assert denial.status == 403


# Selfhost runs Uvicorn with ``--root-path /api/v1``: an upstream ``/health``
# arrives as scope path ``/api/v1/health`` with root_path ``/api/v1``. These
# build that scope (ASGITransport passes the request path through as-is).
_ROOT_PATHS = ["", "/api/v1"]


async def _rooted_client(
    service: PlatformTokenService, monkeypatch: pytest.MonkeyPatch, root_path: str
) -> AsyncClient:
    from syn_api import _wiring
    from syn_api.main import create_app

    monkeypatch.setattr(_wiring, "_platform_token_service_singleton", service)
    transport = ASGITransport(app=create_app(), root_path=root_path)
    return AsyncClient(transport=transport, base_url="http://envoy-proxy:8081")


@pytest.mark.parametrize("root_path", _ROOT_PATHS)
async def test_scope_is_judged_on_the_router_path_under_any_root_path(
    service: PlatformTokenService, monkeypatch: pytest.MonkeyPatch, root_path: str
) -> None:
    token = await service.issue("exec-pc127")
    async with await _rooted_client(service, monkeypatch, root_path) as c:
        assert (await c.get(f"{root_path}/health", headers=_bearer(token))).status_code == 200
        forbidden = await c.post(f"{root_path}/workflows/wf-1/execute", headers=_bearer(token))
        assert forbidden.status_code == 403
        assert (await c.get(f"{root_path}/workflows", headers=_bearer(token))).status_code == 403
        await service.revoke(token)
        assert (await c.get(f"{root_path}/health", headers=_bearer(token))).status_code == 401


@pytest.mark.parametrize("root_path", _ROOT_PATHS)
async def test_a_framework_redirect_stays_on_the_platform_route(
    service: PlatformTokenService, monkeypatch: pytest.MonkeyPatch, root_path: str
) -> None:
    token = await service.issue("exec-pc127")
    async with await _rooted_client(service, monkeypatch, root_path) as c:
        response = await c.get(f"{root_path}/health/", headers=_bearer(token))
    assert response.status_code == 307
    assert response.headers["location"] == "/syn-platform/api/v1/health"


# ---------------------------------------------------------------------------
# The whole route table, not a sample. A route added later is covered here the
# day it lands: a write route must be refused, and a read route outside the
# allowlist must be refused, whatever its path.

_READ_SEGMENTS = frozenset({"executions", "sessions", "artifacts", "evals", "insights", "health"})
_SENSITIVE_WORDS = ("secret", "credential", "token", "env", "setting", "config", "key", "auth")


def _route_table() -> list[tuple[str, str]]:
    from fastapi.routing import APIRoute

    from syn_api.main import create_app

    table: list[tuple[str, str]] = []
    for route in create_app().routes:
        if isinstance(route, APIRoute):
            table.extend((method, route.path) for method in sorted(route.methods))
    assert len(table) > 50, "route table looks empty; did create_app() change shape?"
    return table


def _concrete(path: str) -> str:
    """A path template with every ``{param}`` filled, so the router can match it."""
    import re

    return re.sub(r"\{[^}]+\}", "x", path)


_ROUTES = _route_table()
_WRITES = [(m, p) for m, p in _ROUTES if m not in ("GET", "HEAD")]
_OUTSIDE_READ = [
    (m, p) for m, p in _ROUTES if m in ("GET", "HEAD") and p.split("/")[1] not in _READ_SEGMENTS
]


@pytest.mark.parametrize(("method", "path"), _WRITES)
async def test_no_write_route_is_reachable_with_a_read_token(
    client: AsyncClient, service: PlatformTokenService, method: str, path: str
) -> None:
    token = await service.issue("exec-pc127")
    response = await client.request(method, _concrete(path), headers=_bearer(token))
    assert response.status_code == 403, (method, path, response.status_code)


@pytest.mark.parametrize(("method", "path"), _OUTSIDE_READ)
async def test_no_read_route_outside_the_allowlist_is_reachable(
    client: AsyncClient, service: PlatformTokenService, method: str, path: str
) -> None:
    token = await service.issue("exec-pc127")
    response = await client.request(method, _concrete(path), headers=_bearer(token))
    assert response.status_code == 403, (method, path, response.status_code)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@pytest.mark.parametrize("segment", sorted(_READ_SEGMENTS))
async def test_every_write_method_is_refused_even_on_a_read_resource(
    client: AsyncClient, service: PlatformTokenService, method: str, segment: str
) -> None:
    token = await service.issue("exec-pc127")
    response = await client.request(method, f"/{segment}/x", headers=_bearer(token))
    assert response.status_code == 403


def _names_sensitive(path: str) -> bool:
    """A literal path segment (not a ``{param}``) names secrets, env or credentials."""
    literals = [seg for seg in path.lower().split("/") if seg and not seg.startswith("{")]
    return any(word in seg for seg in literals for word in _SENSITIVE_WORDS)


def test_no_reachable_route_names_secrets_env_or_credentials() -> None:
    reachable = [
        p for m, p in _ROUTES if m in ("GET", "HEAD") and p.split("/")[1] in _READ_SEGMENTS
    ]
    assert reachable
    leaking = [p for p in reachable if _names_sensitive(p)]
    assert leaking == []


def test_routes_that_do_name_secrets_or_settings_are_all_outside_the_read_scope() -> None:
    sensitive = [p for _, p in _ROUTES if _names_sensitive(p)]
    assert sensitive, "expected the API to have settings/credential routes to check"
    assert all(p.split("/")[1] not in _READ_SEGMENTS for p in sensitive)


async def test_the_token_value_is_never_logged(
    client: AsyncClient, service: PlatformTokenService, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.DEBUG)
    token = await service.issue("exec-pc127")
    await client.get("/executions/x", headers=_bearer(token))
    await client.post("/workflows/wf-1/execute", headers=_bearer(token))
    await service.bound_to_deadline(token, datetime(2026, 10, 7, 12, 30, tzinfo=UTC))
    await service.revoke(token)
    await client.get("/health", headers=_bearer(token))
    assert caplog.records, "expected at least the issue log line"
    secret = token.removeprefix("synpt_")
    assert all(secret not in r.getMessage() for r in caplog.records)
    assert secret not in caplog.text
