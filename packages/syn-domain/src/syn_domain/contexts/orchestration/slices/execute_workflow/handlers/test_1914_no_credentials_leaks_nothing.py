"""A NoCredentials workspace receives no host credential, from any source (#1914).

Every host credential is configured with an invented value: the Claude OAuth
token, the Anthropic API key, a GitHub App installation token, the Codex auth
file and a platform grant. The REAL provision handler runs against the real
(in-memory) WorkspaceService, and every byte that reaches the workspace is
recorded: each ``execute`` (argv and env), each file written, the setup
secrets, and the env the agent is streamed with.

The same scan under HostCredentials is the positive control: it must FIND
every value, so a source left unpopulated cannot make the NoCredentials scan
pass vacuously. The session-store token is a Docker-adapter source and is
covered beside the BackendKit (test_1914_backend_kit.py).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.service import (
    SetupPhaseSecrets,
    WorkspaceBackend,
    WorkspaceService,
)
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_api._wiring_agent_command import _build_agent_command, _build_workspace_prompt
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration._shared.workspace_credential_policy import (
    HOST_CREDENTIALS,
    NO_CREDENTIALS,
    CredentialFreePhaseRefusedError,
    WorkspaceCredentialPolicy,
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.handlers.WorkspaceProvisionHandler import (
    WorkspaceProvisionHandler,
)
from syn_shared.env_constants import (
    ENV_ANTHROPIC_API_KEY,
    ENV_CLAUDE_CODE_OAUTH_TOKEN,
    ENV_CODEX_AUTH_JSON,
)
from syn_shared.settings import reset_settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Collection, Iterator

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

# Invented, never real. Each is distinctive enough that a hit is a leak.
_OAUTH = "sk-ant-oat01-FAKE1914oauth"
_API_KEY = "sk-ant-api03-FAKE1914apikey"
_CODEX = '{"auth_mode":"chatgpt","tokens":{"access_token":"FAKE1914codex"}}'
_CODEX_MARK = "FAKE1914codex"
_GITHUB = "ghs_FAKE1914installation"
_PLATFORM = "syn_pat_FAKE1914platform"

#: setup_phase's codex-auth probe echoes this when the staged file is gone.
_STAGED_PROBE = _STAGED_ABSENT = "STAGED_CREDENTIAL_ABSENT"

_REPO = "https://github.com/syntropic137/syntropic137"


@dataclass
class _Recorder:
    """Every string that reached the workspace, by where it went."""

    executes: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    setup_secrets: list[str] = field(default_factory=list)
    stream_envs: list[str] = field(default_factory=list)

    def haystack(self) -> str:
        return "\n".join([*self.executes, *self.files, *self.setup_secrets, *self.stream_envs])


@dataclass(frozen=True)
class _Minted:
    token: str
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + timedelta(hours=1))


class _FakeGitHubClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def __aenter__(self) -> _FakeGitHubClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get_installation_for_repo(self, full_name: str) -> str:
        del full_name
        return "inst-1914"

    async def mint_agent_token(
        self, installation_id: str, *, repositories: Collection[str] | None = None
    ) -> _Minted:
        del installation_id, repositories
        return _Minted(_GITHUB)

    async def revoke_installation_token(self, token: str) -> None:
        del token

    async def close(self) -> None:
        return None


@pytest.fixture
def every_host_credential(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(ENV_CLAUDE_CODE_OAUTH_TOKEN, _OAUTH)
    monkeypatch.setenv(ENV_ANTHROPIC_API_KEY, _API_KEY)
    monkeypatch.setenv(ENV_CODEX_AUTH_JSON, _CODEX)
    reset_settings()
    app = MagicMock(is_configured=True, bot_name="syn-bot", bot_email="bot@example.com")
    with (
        patch("syn_adapters.github.GitHubAppClient", _FakeGitHubClient),
        patch("syn_shared.settings.github.GitHubAppSettings", return_value=app),
        patch(
            "syn_adapters.github.client_endpoints.get_installation_for_repo",
            AsyncMock(return_value="inst-1914"),
        ),
    ):
        yield
    reset_settings()


def _phase() -> ExecutablePhase:
    # allow_delegation stages BOTH harnesses' auth: the widest credential
    # surface a phase can ask for, so every source is exercised at once.
    return ExecutablePhase(
        phase_id="scripted",
        name="Scripted",
        order=1,
        prompt_template="run the script",
        agent_config=AgentConfiguration(provider="claude", allow_delegation=True),
    )


def _service(policy: WorkspaceCredentialPolicy, recorder: _Recorder) -> WorkspaceService:
    platform_tokens = MagicMock()
    # ManagedWorkspace.stream merges a grant's env into the agent's (ADR-072).
    grant = MagicMock(token=_PLATFORM, env={"SYN_API_TOKEN": _PLATFORM})
    platform_tokens.grant_workspace = AsyncMock(return_value=grant)
    platform_tokens.bound_to_deadline = AsyncMock()
    platform_tokens.revoke = AsyncMock()
    service = WorkspaceService.create(
        backend=WorkspaceBackend.MEMORY,
        credential_policy=policy,
        platform_tokens=platform_tokens,
    )
    isolation = service._isolation
    real_execute, real_copy_to = isolation.execute, isolation.copy_to
    real_stream = service._event_stream.stream

    async def execute(handle: object, command: list[str], **kwargs: object) -> object:
        recorder.executes.append(f"{command!r} {kwargs.get('environment')!r}")
        result = await real_execute(handle, command, **kwargs)  # type: ignore[arg-type]
        if any(_STAGED_PROBE in part for part in command):
            # The double runs nothing, so it cannot answer the codex-auth
            # removal probe; answer it as a workspace whose cleanup worked.
            return replace(result, stdout=f"{_STAGED_ABSENT}\n")
        return result

    async def copy_to(handle: object, files: list[tuple[str, bytes]], **kwargs: str) -> None:
        recorder.files.extend(f"{path} {content!r}" for path, content in files)
        await real_copy_to(handle, files, **kwargs)  # type: ignore[arg-type]

    def stream(handle: object, command: list[str], **kwargs: object) -> AsyncIterator[str]:
        recorder.stream_envs.append(f"{command!r} {kwargs.get('environment')!r}")
        return real_stream(handle, command, **kwargs)  # type: ignore[arg-type]

    isolation.execute = execute  # type: ignore[method-assign]
    isolation.copy_to = copy_to  # type: ignore[method-assign]
    service._event_stream.stream = stream  # type: ignore[method-assign]
    return service


async def _provision(
    policy: WorkspaceCredentialPolicy, repos: list[str]
) -> tuple[_Recorder, WorkspaceService]:
    recorder = _Recorder()
    service = _service(policy, recorder)
    real_run_setup = ManagedWorkspace.run_setup_phase

    async def run_setup_phase(self: ManagedWorkspace, secrets: SetupPhaseSecrets) -> object:
        # What reaches the workspace, whichever way the handler built it.
        recorder.setup_secrets.append(repr(asdict(secrets)))
        return await real_run_setup(self, secrets)

    handler = WorkspaceProvisionHandler(
        workspace_service=service,
        prompt_builder=_build_workspace_prompt,
        command_builder=_build_agent_command,
    )
    todo = TodoItem(
        execution_id="exec-1914", action=TodoAction.PROVISION_WORKSPACE, phase_id="scripted"
    )
    with patch.object(ManagedWorkspace, "run_setup_phase", run_setup_phase):
        result = await handler.handle(
            todo=todo,
            phase=_phase(),
            workflow_id="wf-1914",
            session_id="sess-1914",
            repos=repos,
        )
    try:
        # What AgentExecutionHandler does with the result: stream the agent.
        async for _ in result.workspace.stream(result.claude_cmd, environment=result.agent_env):
            pass
        if result.fallback is not None:
            async for _ in result.workspace.stream(
                result.fallback.claude_cmd, environment=result.fallback.agent_env
            ):
                pass
    finally:
        await result.workspace_cm.__aexit__(None, None, None)
    return recorder, service


_SECRETS = {
    "claude oauth token": _OAUTH,
    "anthropic api key": _API_KEY,
    "codex auth": _CODEX_MARK,
    "github app token": _GITHUB,
    "platform grant": _PLATFORM,
}


@pytest.mark.usefixtures("every_host_credential")
class TestNoCredentialsLeaksNothing:
    async def test_host_credentials_populate_every_source(self) -> None:
        """Positive control: under HostCredentials every invented value IS found."""
        recorder, _ = await _provision(HOST_CREDENTIALS, [_REPO])

        haystack = recorder.haystack()
        assert recorder.setup_secrets, "the setup phase was never run"
        assert recorder.stream_envs, "the agent was never streamed"
        missing = [name for name, value in _SECRETS.items() if value not in haystack]
        assert missing == [], f"sources never populated, so absence would prove nothing: {missing}"

    async def test_no_credentials_scan_finds_none(self) -> None:
        recorder, _ = await _provision(NO_CREDENTIALS, [])

        assert recorder.executes, "nothing was executed, so the scan saw nothing"
        assert recorder.setup_secrets, "the setup phase was never run"
        assert recorder.stream_envs, "the agent was never streamed"
        for where, entries in asdict(recorder).items():
            text = "\n".join(entries)
            leaked = [name for name, value in _SECRETS.items() if value in text]
            assert leaked == [], f"{leaked} reached the workspace through {where}"

    async def test_a_phase_with_repos_is_refused_before_create_workspace(self) -> None:
        service = MagicMock()
        service.credential_policy = NO_CREDENTIALS
        handler = WorkspaceProvisionHandler(
            workspace_service=service,
            prompt_builder=_build_workspace_prompt,
            command_builder=_build_agent_command,
        )
        todo = TodoItem(
            execution_id="e", action=TodoAction.PROVISION_WORKSPACE, phase_id="scripted"
        )

        with pytest.raises(CredentialFreePhaseRefusedError, match="credential-free"):
            await handler.handle(
                todo=todo, phase=_phase(), workflow_id="wf", session_id="s", repos=[_REPO]
            )
        service.create_workspace.assert_not_called()

    async def test_the_service_refuses_a_sidecar_for_a_credential_free_workspace(self) -> None:
        """A caller that ignores the policy cannot get a sidecar or tokens anyway."""
        service = WorkspaceService.create(
            backend=WorkspaceBackend.MEMORY, credential_policy=NO_CREDENTIALS
        )
        with pytest.raises(ValueError, match="no sidecar"):
            async with service.create_workspace(execution_id="e", with_sidecar=True):
                pass
