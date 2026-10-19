"""A NoCredentials workspace receives no host credential, from any source (#1914).

Every host credential is configured with an invented value: the Claude OAuth
token, the Anthropic API key, a GitHub App installation token, the Codex auth
file, a platform grant and the session-store write token. The REAL provision
handler runs against the real (in-memory) WorkspaceService, and every byte that
reaches the workspace is recorded: each ``execute`` (argv and env), each file
written, the setup secrets, and the env the agent is streamed with. The
session-store token lives in the Docker adapter, so the real policy-bearing
``AgenticIsolationAdapter`` also creates the workspace against a recording
provider, and what its container would be given - environment, labels and
every credential binding, resolved - is the fifth channel.

The same scan under HostCredentials, with the SAME repo-less phase, is the
positive control: it must FIND every value, so a source left unpopulated
cannot make the NoCredentials scan pass vacuously. The scan test runs it
first, so a mutation run that selects only the scan still proves population.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentic_isolation.providers.base import ExecuteResult

from syn_adapters.workspace_backends.agentic.adapter import AgenticIsolationAdapter
from syn_adapters.workspace_backends.backend_kit import BackendKit
from syn_adapters.workspace_backends.service import (
    SetupPhaseSecrets,
    WorkspaceBackend,
    WorkspaceService,
)
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_api._wiring_agent_command import _build_agent_command, _build_workspace_prompt
from syn_domain.contexts.orchestration import (
    HOST_CREDENTIALS,
    NO_CREDENTIALS,
    CredentialFreePhaseRefusedError,
    WorkspaceCredentialPolicy,
)
from syn_domain.contexts.orchestration._shared.TodoValueObjects import TodoAction, TodoItem
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    IsolationConfig,
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
_SESSION_STORE = "FAKE1914-session-store-write-token"
_SESSION_STORE_URL = "https://sessions.fake1914.invalid"
# Invented: no stub image is pinned yet (step H). Never a real digest.
_STUB = "ghcr.io/example/scripted-stub@sha256:" + "19" * 32
#: Stands in for a proxy only where none exists, so a bypassed agent-env
#: builder gets past its proxy check and the scan sees what it would send.
_INERT_PROXY = "http://inert-proxy.fake1914.invalid"

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
    container: list[str] = field(default_factory=list)

    def haystack(self) -> str:
        return "\n".join(
            [
                *self.executes,
                *self.files,
                *self.setup_secrets,
                *self.stream_envs,
                *self.container,
            ]
        )


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

    async def list_installations(self) -> list[dict[str, str]]:
        # The shape a repo-less phase mints its gh credential from.
        return [{"id": "inst-1914"}]

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
    monkeypatch.setenv("SYN_SESSION_STORE_URL", _SESSION_STORE_URL)
    monkeypatch.setenv("SYN_SESSION_STORE_AUTH_TOKEN", _SESSION_STORE)
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


async def _record_container(policy: WorkspaceCredentialPolicy, recorder: _Recorder) -> None:
    """What the real Docker adapter, under ``policy``, would hand its container.

    The session store is read from host settings, as production does. Every
    credential binding is resolved, so a token delivered by reference counts.
    """
    kit = BackendKit(
        default_image=_STUB, credential_policy=policy, credential_free_images=frozenset({_STUB})
    )
    adapter = AgenticIsolationAdapter(kit=kit)
    workspace = MagicMock(id="ws-1914", metadata={"workspace_dir": "/workspace"})
    provider = MagicMock(
        create=AsyncMock(return_value=workspace),
        execute=AsyncMock(return_value=ExecuteResult(exit_code=0, stdout="", stderr="")),
    )
    with (
        patch.object(adapter, "_provider", provider),
        patch(
            "syn_adapters.workspace_backends.backend_kit.verify_image_async",
            AsyncMock(return_value=_STUB),
        ),
    ):
        await adapter.create(
            IsolationConfig(
                execution_id="exec-1914", workspace_id="ws-1914", phase_id="scripted", image=_STUB
            )
        )
    (ws_config,) = provider.create.call_args.args
    resolved = [await adapter.credentials.resolve(b.ref) for b in ws_config.credentials]
    recorder.container.append(f"{ws_config.environment!r} {ws_config.labels!r} {resolved!r}")


async def _provision(
    policy: WorkspaceCredentialPolicy, repos: list[str]
) -> tuple[_Recorder, WorkspaceService]:
    recorder = _Recorder()
    await _record_container(policy, recorder)
    service = _service(policy, recorder)
    real_proxy_url = ManagedWorkspace.proxy_url
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
    with (
        patch.object(ManagedWorkspace, "run_setup_phase", run_setup_phase),
        patch.object(
            ManagedWorkspace,
            "proxy_url",
            property(lambda ws: real_proxy_url.fget(ws) or _INERT_PROXY),  # type: ignore[union-attr]
        ),
    ):
        result = await handler.handle(
            todo=todo,
            phase=_phase(),
            workflow_id="wf-1914",
            session_id="sess-1914",
            repos=repos,
        )
    try:
        # The credential keeper renews the git credential while the agent runs.
        await result.workspace.renew_git_credential()
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
    "session-store token": _SESSION_STORE,
}


def _assert_every_source_populated(recorder: _Recorder) -> None:
    haystack = recorder.haystack()
    assert recorder.setup_secrets, "the setup phase was never run"
    assert recorder.stream_envs, "the agent was never streamed"
    missing = [name for name, value in _SECRETS.items() if value not in haystack]
    assert missing == [], f"sources never populated, so absence would prove nothing: {missing}"
    # Renewal rewrites the gh credential file: the token must reach a file.
    assert _GITHUB in "\n".join(recorder.files), "the GitHub token never reached a file"


@pytest.mark.usefixtures("every_host_credential")
class TestNoCredentialsLeaksNothing:
    async def test_host_credentials_populate_every_source(self) -> None:
        """Positive control with repositories: every invented value IS found."""
        recorder, _ = await _provision(HOST_CREDENTIALS, [_REPO])

        _assert_every_source_populated(recorder)

    async def test_no_credentials_scan_finds_none(self) -> None:
        # Positive control first, on the same repo-less shape the scan runs.
        host, _ = await _provision(HOST_CREDENTIALS, [])
        _assert_every_source_populated(host)

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
