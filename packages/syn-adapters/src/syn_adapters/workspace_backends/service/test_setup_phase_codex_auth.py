"""Codex authentication tests for the ADR-024 setup phase."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_adapters.workspace_backends.service.setup_phase import (
    _build_setup_env,
    clear_secrets,
    run_setup_phase,
)
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)


def _workspace() -> MagicMock:
    workspace = MagicMock(spec=ManagedWorkspace)
    workspace.workspace_id = "workspace-codex-auth"
    workspace.inject_files = AsyncMock()
    workspace.execute = AsyncMock()
    return workspace


@pytest.mark.unit
def test_codex_auth_written_even_without_repos() -> None:
    secrets = SetupPhaseSecrets.for_testing(codex_auth_json='{"tokens":{"access_token":"secret"}}')

    assert secrets.repositories == []
    script = secrets.build_setup_script()
    assert "mkdir -p -m 700 ~/.codex" in script
    assert "install -m 600 /workspace/.setup/codex-auth.json ~/.codex/auth.json" in script
    assert "rm -f /workspace/.setup/codex-auth.json" in script
    assert "secret" not in script


@pytest.mark.unit
@pytest.mark.anyio
async def test_codex_auth_scoped_to_codex_phases() -> None:
    # A claude phase (include_codex_auth=False) must NOT resolve/carry the codex
    # credential, so a non-codex phase's agent can never read the OpenAI auth.
    with patch(
        "syn_adapters.workspace_backends.service.setup_phase_secrets._resolve_codex_credentials",
        return_value='{"a":1}',
    ):
        claude_secrets = await SetupPhaseSecrets.create(
            require_github=False, include_codex_auth=False
        )
        codex_secrets = await SetupPhaseSecrets.create(
            require_github=False, include_codex_auth=True
        )

    assert claude_secrets.codex_auth_json is None
    assert codex_secrets.codex_auth_json == '{"a":1}'


@pytest.mark.unit
def test_codex_auth_not_in_setup_env() -> None:
    secrets = SetupPhaseSecrets.for_testing(codex_auth_json='{"a":1}')

    assert "CODEX_AUTH_JSON" not in _build_setup_env(secrets)


@pytest.mark.unit
@pytest.mark.anyio
async def test_run_setup_phase_injects_codex_auth_as_file() -> None:
    workspace = _workspace()
    workspace.execute.return_value = ExecutionResult(
        exit_code=0,
        success=True,
        duration_ms=1,
        stdout="",
        stderr="",
    )
    secrets = SetupPhaseSecrets.for_testing(codex_auth_json='{"a":1}')

    with patch(
        "syn_adapters.workspace_backends.service.setup_phase.clear_secrets",
        new=AsyncMock(),
    ):
        await run_setup_phase(workspace, secrets)

    # Staged under .setup/ at the /workspace mount (the docker copy path ignores
    # base_path); the setup script relocates it to ~/.codex/auth.json with 0600.
    workspace.inject_files.assert_any_await(
        [(".setup/codex-auth.json", b'{"a":1}')],
        base_path="/workspace",
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_cleanup_runs_when_setup_fails() -> None:
    workspace = _workspace()
    workspace.execute.return_value = ExecutionResult(
        exit_code=7,
        success=False,
        duration_ms=1,
        stdout="",
        stderr="failed",
    )
    secrets = SetupPhaseSecrets.for_testing(codex_auth_json='{"a":1}')
    cleanup = AsyncMock()

    with patch(
        "syn_adapters.workspace_backends.service.setup_phase.clear_secrets",
        new=cleanup,
    ):
        result = await run_setup_phase(workspace, secrets)

    assert result.exit_code == 7
    cleanup.assert_awaited_once_with(workspace)


@pytest.mark.unit
@pytest.mark.anyio
async def test_cleanup_runs_when_codex_injection_fails() -> None:
    # The codex-auth staging is INSIDE the try, so a failed injection still runs
    # clear_secrets in the finally - no credential is left staged under /workspace.
    workspace = _workspace()
    # inject #1 = setup.sh (ok), inject #2 = codex-auth (raises)
    workspace.inject_files = AsyncMock(side_effect=[None, RuntimeError("inject boom")])
    workspace.execute.return_value = ExecutionResult(
        exit_code=0, success=True, duration_ms=1, stdout="", stderr=""
    )
    secrets = SetupPhaseSecrets.for_testing(codex_auth_json='{"a":1}')
    cleanup = AsyncMock()

    with patch(
        "syn_adapters.workspace_backends.service.setup_phase.clear_secrets",
        new=cleanup,
    ):
        with pytest.raises(RuntimeError, match="inject boom"):
            await run_setup_phase(workspace, secrets)

    cleanup.assert_awaited_once_with(workspace)


@pytest.mark.unit
@pytest.mark.anyio
async def test_codex_auth_survives_clear_secrets() -> None:
    workspace = _workspace()
    workspace.execute.return_value = ExecutionResult(
        exit_code=0,
        success=True,
        duration_ms=1,
        stdout="",
        stderr="",
    )

    await clear_secrets(workspace)

    cleanup_script = workspace.inject_files.await_args.args[0][0][1].decode()
    assert "/workspace/.setup" in cleanup_script
    assert "~/.codex" not in cleanup_script
    assert "auth.json" not in cleanup_script
