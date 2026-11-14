"""A run that names a repository is refused at execute when no GitHub App is configured (#1948).

Before #1948 the route admitted it, and the run failed in workspace setup about
30 seconds later, with env var names that do not exist on a selfhost install.
The refusal now comes first, as a 422 naming the fix, and nothing is launched.
A run that names no repository needs no App and is still admitted.

Everything goes through the real app and the real execute route; only
``execute()`` is replaced, so "launched" means the route handed the request on.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.maintenance import InMemoryMaintenanceAdapter
from syn_domain.contexts._shared import AdmissionGate

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

    from syn_domain.contexts._shared import AdmissionTicket

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

REPO = "https://github.com/syntropic137/syntropic137"


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
def no_github_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """A server with no GitHub App, whatever the machine running the test has set."""
    from syn_shared.settings.github import GitHubAppSettings

    unconfigured = GitHubAppSettings.model_construct()
    monkeypatch.setattr("syn_api._wiring.get_github_settings", lambda: unconfigured)


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


async def _create_workflow(*, requires_repos: bool) -> str:
    from syn_api.routes.workflows import create_workflow
    from syn_api.types import Ok

    created = await create_workflow(
        name="GitHub App #1948",
        workflow_type="research",
        requires_repos=requires_repos,
        phases=[{"name": "Work", "prompt_template": "Summarise the repository."}],
    )
    assert isinstance(created, Ok)
    return created.value.workflow_id


@pytest.mark.usefixtures("no_github_app")
@pytest.mark.parametrize("requires_repos", [True, False], ids=["requires-repos", "optional"])
async def test_a_run_naming_a_repo_is_refused_with_the_fix_and_launches_nothing(
    client: AsyncClient, execution: _CapturingExecute, requires_repos: bool
) -> None:
    workflow_id = await _create_workflow(requires_repos=requires_repos)

    response = await client.post(f"/workflows/{workflow_id}/execute", json={"repos": [REPO]})

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "GitHub App is not configured" in detail
    assert "SYN_GITHUB_APP_ID" in detail
    assert "SYN_GITHUB_APP_PRIVATE_KEY_FILE" in detail
    assert "npx @syntropic137/setup init" in detail
    assert "https://docs.syntropic137.com/docs/guide/github-integration" in detail
    assert execution.launched == 0


@pytest.mark.usefixtures("github_app_configured")
async def test_the_same_run_is_admitted_once_the_app_is_configured(
    client: AsyncClient, execution: _CapturingExecute
) -> None:
    workflow_id = await _create_workflow(requires_repos=True)

    response = await client.post(f"/workflows/{workflow_id}/execute", json={"repos": [REPO]})

    assert response.status_code == 200, response.text
    assert execution.launched == 1


@pytest.mark.usefixtures("no_github_app")
async def test_a_run_naming_no_repo_is_admitted_without_an_app(
    client: AsyncClient, execution: _CapturingExecute
) -> None:
    workflow_id = await _create_workflow(requires_repos=False)

    response = await client.post(f"/workflows/{workflow_id}/execute", json={})

    assert response.status_code == 200, response.text
    assert execution.launched == 1


@pytest.fixture
def half_configured_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest
) -> Iterator[None]:
    """An App ID whose private key is unusable, loaded from the environment for real.

    Settings validation rejects this shape, which /health reports as `github_app`
    degraded; before the fix the execute route answered it with a 500.
    """
    from syn_shared.settings.github import GitHubAppSettings, reset_github_settings

    key_file = tmp_path / "app.pem"
    if request.param == "empty-pem":
        key_file.write_text("")
    monkeypatch.chdir(tmp_path)  # no stray .env supplies a key
    for field in GitHubAppSettings.model_fields:
        monkeypatch.delenv(GitHubAppSettings.env_var(field), raising=False)
    monkeypatch.setenv(GitHubAppSettings.env_var("app_id"), "1948")
    monkeypatch.setenv(GitHubAppSettings.env_var("app_private_key_file"), str(key_file))
    reset_github_settings()
    yield
    reset_github_settings()


@pytest.mark.parametrize("half_configured_app", ["missing-pem", "empty-pem"], indirect=True)
@pytest.mark.usefixtures("half_configured_app")
async def test_a_half_configured_app_is_refused_with_the_fix_not_a_500(
    client: AsyncClient, execution: _CapturingExecute
) -> None:
    from syn_shared.settings.github import not_configured_message

    workflow_id = await _create_workflow(requires_repos=True)

    response = await client.post(f"/workflows/{workflow_id}/execute", json={"repos": [REPO]})

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == not_configured_message()
    assert execution.launched == 0
