"""A Claude run with no Anthropic credential is a 422 at execute, never a run (#1948).

Before #1948 the run was admitted, and failed mid-run, while `/health` already
reported the `anthropic_api_key` degraded reason. Admission and `/health` now
ask one predicate, so every case below is also checked against `/health`.

Everything goes through the real app and the real execute route; only
``execute()`` is replaced, so "launched" means the route handed the request on.
Settings are swapped for a non-test copy only where the refusal and `/health`
read them: under test settings neither reports the credential missing.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_domain.contexts._shared import AdmissionGate
from syn_shared.agents import AgentProvider
from syn_shared.env_constants import ENV_ANTHROPIC_API_KEY, ENV_CLAUDE_CODE_OAUTH_TOKEN
from syn_shared.settings import AppEnvironment, get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

    from syn_domain.contexts._shared import AdmissionTicket

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    if hasattr(store, "_state"):
        store._state.clear()  # pyright: ignore[reportAttributeAccessIssue]  # in-memory store only
    yield
    reset_storage()
    reset_projection_manager()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


class _CapturingExecute:
    """Stands in for `execute()`, counting each launch the route admitted."""

    def __init__(self) -> None:
        self.launched = 0

    async def __call__(self, *, admitted: AdmissionTicket | None = None, **_: object) -> None:
        self.launched += 1
        if admitted is not None:
            admitted.mark_visible()


@pytest.fixture
def execution(monkeypatch: pytest.MonkeyPatch) -> _CapturingExecute:
    import syn_api._wiring_admission as wiring
    from syn_api.routes.executions import commands

    captured = _CapturingExecute()
    monkeypatch.setattr(
        wiring,
        "_admission_gate_singleton",
        AdmissionGate(InMemoryMaintenanceAdapter()),
        raising=False,
    )
    monkeypatch.setattr(commands, "execute", captured)
    return captured


def _configure(
    monkeypatch: pytest.MonkeyPatch, environment: AppEnvironment
) -> Callable[[str | None, str | None], None]:
    import syn_shared.settings as shared_settings
    from syn_api.routes.executions import credential_access

    # validate_credentials exports the API key; keep that out of other tests.
    monkeypatch.delenv(ENV_ANTHROPIC_API_KEY, raising=False)

    def apply(api_key: str | None, oauth_token: str | None) -> None:
        deployed = get_settings().model_copy(
            update={
                "app_environment": environment,
                "anthropic_api_key": SecretStr(api_key) if api_key is not None else None,
                "claude_code_oauth_token": (
                    SecretStr(oauth_token) if oauth_token is not None else None
                ),
            }
        )
        monkeypatch.setattr(credential_access, "get_settings", lambda: deployed)
        # validate_credentials imports get_settings from here at call time.
        monkeypatch.setattr(shared_settings, "get_settings", lambda: deployed)

    return apply


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> Callable[[str | None, str | None], None]:
    """Configure a deployment (not test) with the given Anthropic credentials."""
    return _configure(monkeypatch, AppEnvironment.DEVELOPMENT)


def _health_says_claude_credential_missing() -> bool:
    from syn_api.services.credentials import validate_credentials
    from syn_api.services.degraded_reasons import DegradedReason

    reasons: list[DegradedReason] = []
    validate_credentials(reasons)
    return DegradedReason.ANTHROPIC_API_KEY in reasons


async def _create_workflow(*providers: str | None) -> str:
    from syn_api.routes.workflows import create_workflow
    from syn_api.types import Ok

    phases = [
        {"name": f"Work {i}", "prompt_template": "do it", "provider": provider}
        for i, provider in enumerate(providers)
    ]
    created = await create_workflow(
        name="Credential #1948", workflow_type="research", requires_repos=False, phases=phases
    )
    assert isinstance(created, Ok)
    return created.value.workflow_id


async def test_a_claude_phase_with_no_credential_is_refused(
    client: AsyncClient,
    execution: _CapturingExecute,
    credentials: Callable[[str | None, str | None], None],
) -> None:
    workflow_id = await _create_workflow(AgentProvider.CLAUDE)
    credentials(None, "")

    response = await client.post(f"/workflows/{workflow_id}/execute", json={})

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert ENV_ANTHROPIC_API_KEY in detail
    assert ENV_CLAUDE_CODE_OAUTH_TOKEN in detail
    assert "either one is enough" in detail
    assert "npx @syntropic137/setup init" in detail
    assert "docs.syntropic137.com/docs/guide/secrets#harness-credentials" in detail
    # Refused in request validation, before admission and before any
    # execution is requested, so nothing was handed on to start.
    assert execution.launched == 0
    assert _health_says_claude_credential_missing()


async def test_an_unset_provider_is_claude_and_is_refused(
    client: AsyncClient,
    execution: _CapturingExecute,
    credentials: Callable[[str | None, str | None], None],
) -> None:
    """A phase that names no provider runs on Claude, so it needs the credential."""
    workflow_id = await _create_workflow(AgentProvider.CODEX, None)
    credentials(None, None)

    response = await client.post(f"/workflows/{workflow_id}/execute", json={})

    assert response.status_code == 422, response.text
    assert execution.launched == 0


@pytest.mark.parametrize(
    ("api_key", "oauth_token"),
    [("sk-ant-api-only", None), (None, "sk-ant-oat-only")],
    ids=["api-key-only", "oauth-token-only"],
)
async def test_either_credential_alone_is_admitted(
    client: AsyncClient,
    execution: _CapturingExecute,
    credentials: Callable[[str | None, str | None], None],
    api_key: str | None,
    oauth_token: str | None,
) -> None:
    workflow_id = await _create_workflow(AgentProvider.CLAUDE)
    credentials(api_key, oauth_token)

    response = await client.post(f"/workflows/{workflow_id}/execute", json={})

    assert response.status_code == 200, response.text
    assert execution.launched == 1
    assert not _health_says_claude_credential_missing()


async def test_a_codex_only_workflow_needs_no_anthropic_credential(
    client: AsyncClient,
    execution: _CapturingExecute,
    credentials: Callable[[str | None, str | None], None],
) -> None:
    workflow_id = await _create_workflow(AgentProvider.CODEX)
    credentials(None, None)

    response = await client.post(f"/workflows/{workflow_id}/execute", json={})

    assert response.status_code == 200, response.text
    assert execution.launched == 1
    # /health still reports it: a Claude run on this deployment would be refused.
    assert _health_says_claude_credential_missing()


async def test_test_settings_admit_as_health_stays_quiet(
    client: AsyncClient, execution: _CapturingExecute, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under test settings neither /health nor admission reports the credential
    missing, which is what keeps every other execute test credential-free."""
    _configure(monkeypatch, AppEnvironment.TEST)(None, None)
    workflow_id = await _create_workflow(AgentProvider.CLAUDE)

    response = await client.post(f"/workflows/{workflow_id}/execute", json={})

    assert response.status_code == 200, response.text
    assert execution.launched == 1
    assert not _health_says_claude_credential_missing()
