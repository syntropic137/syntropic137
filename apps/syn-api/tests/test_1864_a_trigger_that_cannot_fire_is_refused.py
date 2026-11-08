"""Creating a trigger that could never fire is refused, and nothing is stored (#1864).

A trigger on a repository fires through a GitHub App installation. Before
#1864, a server with no App, or an App with no installation on the repository,
stored the rule `active` with `installation_id=''`. Dispatch then skipped it
forever without saying so (release rehearsal 2026-10-10).

These drive the HTTP route, which is what `syn triggers register` calls, and
then read the trigger list back, because "refused" only matters if nothing
was stored behind it.
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient, Response

from syn_api.types import Ok, TriggerError, TriggerErrorResponse

pytestmark = pytest.mark.unit

os.environ.setdefault("APP_ENVIRONMENT", "test")

_REPO = "acme/widgets"
_WORKFLOW = "wf-1864"

# The exact words `GET /github/repos` answers with when there is no App
# (`get_github_client`, baca940). Asserted whole, so a paraphrase fails.
_NOT_CONFIGURED = (
    "GitHub App not configured. Set SYN_GITHUB_APP_ID and either "
    "SYN_GITHUB_APP_PRIVATE_KEY_FILE or SYN_GITHUB_PRIVATE_KEY."
)


@pytest.fixture(autouse=True)
async def _fresh_stores_with_a_workflow():
    import syn_api._wiring
    from syn_adapters.storage import reset_storage
    from syn_adapters.storage.repositories import get_workflow_repository
    from syn_api._wiring import ensure_connected
    from syn_domain.contexts.github.slices.register_trigger.trigger_store import (
        reset_trigger_store,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
        PhaseDefinition,
        WorkflowClassification,
        WorkflowType,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.CreateWorkflowTemplateCommand import (
        CreateWorkflowTemplateCommand,
    )

    reset_storage()
    reset_trigger_store()
    syn_api._wiring._test_trigger_repo = None
    await ensure_connected()

    aggregate = WorkflowTemplateAggregate()
    aggregate._handle_command(
        CreateWorkflowTemplateCommand(
            aggregate_id=_WORKFLOW,
            name="workflow-1864",
            workflow_type=WorkflowType.CUSTOM,
            classification=WorkflowClassification.SIMPLE,
            repository_url="https://github.com/acme/widgets",
            repository_ref="main",
            phases=[PhaseDefinition(phase_id="phase-1", name="phase1", order=1)],
        )
    )
    await get_workflow_repository().save(aggregate)
    yield
    reset_trigger_store()
    syn_api._wiring._test_trigger_repo = None


@pytest.fixture
def no_github_app(monkeypatch: pytest.MonkeyPatch):
    """A server whose operator has not set up the GitHub App: the real factory refuses.

    Each variable is set empty rather than deleted. Deleted, `GitHubAppSettings`
    falls through to its `.env` source and a developer's configured App comes
    back; an empty environment value outranks the dotenv file.
    """
    import syn_adapters.github.client as client_module
    from syn_shared.settings import reset_settings

    for var in (
        "SYN_GITHUB_APP_ID",
        "SYN_GITHUB_APP_PRIVATE_KEY_FILE",
        "SYN_GITHUB_PRIVATE_KEY",
    ):
        monkeypatch.setenv(var, "")
    monkeypatch.setattr(client_module, "_github_client", None)
    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def developer_dotenv_configures_the_app(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """A developer `.env` that configures an App, as a real checkout may have."""
    from syn_shared.settings.github import GitHubAppSettings

    dotenv = tmp_path / ".env"
    dotenv.write_text("SYN_GITHUB_APP_ID=123\nSYN_GITHUB_PRIVATE_KEY=synthetic-not-a-key\n")
    monkeypatch.setitem(GitHubAppSettings.model_config, "env_file", str(dotenv))


class _InstalledNowhere:
    """A configured App that GitHub says is not installed on the repository."""

    async def get_installation_for_repo(self, repo_full_name: str) -> str:
        from syn_adapters.github.client import GitHubAuthError

        raise GitHubAuthError(f"GitHub App not installed on repository: {repo_full_name}")


async def _create(path: str, body: dict[str, str]) -> Response:
    from fastapi import FastAPI

    from syn_api.routes.triggers import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, json=body)


async def _register() -> Response:
    return await _create(
        "/triggers",
        {"name": "on-push", "event": "push", "repository": _REPO, "workflow_id": _WORKFLOW},
    )


async def _enable_preset() -> Response:
    return await _create(
        "/triggers/presets/self-healing", {"repository": _REPO, "workflow_id": _WORKFLOW}
    )


async def _stored_triggers() -> list[object]:
    from syn_api.routes.triggers import list_triggers

    listed = await list_triggers()
    assert isinstance(listed, Ok)
    return list(listed.value)


@pytest.mark.parametrize("create", [_register, _enable_preset], ids=["register", "preset"])
async def test_no_github_app_refuses_with_the_not_configured_message(
    no_github_app: None, create
) -> None:
    response = await create()

    assert response.status_code == 409, response.text
    refusal = TriggerErrorResponse.model_validate_json(response.content)
    assert refusal.code == TriggerError.GITHUB_NOT_CONFIGURED
    assert refusal.detail == _NOT_CONFIGURED
    assert await _stored_triggers() == []


@pytest.mark.parametrize("create", [_register, _enable_preset], ids=["register", "preset"])
async def test_a_developer_dotenv_does_not_reconfigure_the_absent_app(
    developer_dotenv_configures_the_app: None, no_github_app: None, create
) -> None:
    """The no-App fixture holds however the checkout's `.env` is set up."""
    from syn_adapters.github.client import GitHubNotConfiguredError, get_github_client

    with pytest.raises(GitHubNotConfiguredError):
        get_github_client()

    response = await create()

    assert response.status_code == 409, response.text
    refusal = TriggerErrorResponse.model_validate_json(response.content)
    assert refusal.code == TriggerError.GITHUB_NOT_CONFIGURED
    assert refusal.detail == _NOT_CONFIGURED
    assert await _stored_triggers() == []


@pytest.mark.parametrize("create", [_register, _enable_preset], ids=["register", "preset"])
async def test_no_installation_on_the_repository_refuses(
    monkeypatch: pytest.MonkeyPatch, create
) -> None:
    monkeypatch.setattr("syn_adapters.github.client.get_github_client", _InstalledNowhere)

    response = await create()

    assert response.status_code == 409, response.text
    refusal = TriggerErrorResponse.model_validate_json(response.content)
    assert refusal.code == TriggerError.NO_INSTALLATION
    assert _REPO in refusal.detail
    assert "Install the GitHub App" in refusal.detail
    assert await _stored_triggers() == []


async def test_a_repository_that_names_nothing_is_refused(
    github_installation_resolves: object,
) -> None:
    """Neither `repo-*` nor `owner/name`: no installation can even be asked for."""
    response = await _create(
        "/triggers",
        {"name": "on-push", "event": "push", "repository": "widgets", "workflow_id": _WORKFLOW},
    )

    assert response.status_code == 409, response.text
    refusal = TriggerErrorResponse.model_validate_json(response.content)
    assert refusal.code == TriggerError.REPOSITORY_UNRESOLVED
    assert await _stored_triggers() == []


async def test_a_resolved_installation_is_created_as_before(
    github_installation_resolves: object,
) -> None:
    from syn_api.routes.triggers import get_trigger

    response = await _register()

    assert response.status_code == 200, response.text
    trigger_id = response.json()["trigger_id"]
    stored = await get_trigger(trigger_id)
    assert isinstance(stored, Ok)
    assert stored.value.installation_id == "inst-from-github-app"
    assert stored.value.status == "active"


async def test_an_explicit_installation_id_is_taken_as_given(no_github_app: None) -> None:
    """Supplying the installation skips resolution, App or not, as before."""
    from syn_api.routes.triggers import get_trigger

    response = await _create(
        "/triggers",
        {
            "name": "on-push",
            "event": "push",
            "repository": _REPO,
            "workflow_id": _WORKFLOW,
            "installation_id": "inst-given",
        },
    )

    assert response.status_code == 200, response.text
    stored = await get_trigger(response.json()["trigger_id"])
    assert isinstance(stored, Ok)
    assert stored.value.installation_id == "inst-given"
