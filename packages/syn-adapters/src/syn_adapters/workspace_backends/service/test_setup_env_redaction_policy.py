"""The setup environment must be registrable with agentic-workspace's redactor.

1.0.4-beta.1 (AW be32a683, spool credential redaction) failed every run at
secret-injection setup with ``rejected_policy: a registered redaction value
overlaps the redaction marker``. Every value in the setup ``environment`` is
registered for redaction (``DockerOperations.start``: ``delivered_env`` ->
``OperationSpool(redact=...)``), and AW refuses a value holding ``[`` or ``]``.

The trigger was NOT an empty ``ANTHROPIC_API_KEY``: an empty value is never
put in the environment and AW skips empties anyway. It was the GitHub App git
identity, ``<app>[bot]`` and ``<id>+<app>[bot]@users.noreply.github.com``.

These drive the REAL AW spool, not a double: the environment is the one
``run_setup_phase`` hands to ``execute``, and it goes into the same
``OperationSpool`` constructor the docker provider uses. Diagnostics name env
vars and lengths only, never values.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentic_isolation.providers.operation_spool import OperationFailure, OperationSpool

from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_adapters.workspace_backends.service.setup_phase import run_setup_phase
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_shared.env_constants import ENV_ANTHROPIC_API_KEY, ENV_CLAUDE_CODE_OAUTH_TOKEN
from syn_shared.settings.github import GitHubAppSettings

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_FAKE_OAUTH = "sk-ant-oat01-fake-setup-redaction-token"
_GITHUB = GitHubAppSettings(app_id="123456", app_name="syntropic137", private_key="unused")


def _secrets(*, anthropic_api_key: str = "") -> SetupPhaseSecrets:
    """What `SetupPhaseSecrets.create` builds with a GitHub App configured."""
    return SetupPhaseSecrets(
        claude_code_oauth_token=_FAKE_OAUTH,
        anthropic_api_key=anthropic_api_key,
        git_author_name=_GITHUB.bot_name,
        git_author_email=_GITHUB.bot_email,
    )


async def _setup_environment(secrets: SetupPhaseSecrets) -> tuple[dict[str, str], str]:
    """The environment and script the setup run hands to `execute`."""
    ws = MagicMock(spec=ManagedWorkspace)
    ws.workspace_id = "workspace-redaction-policy"
    ws.inject_files = AsyncMock()
    ws.execute = AsyncMock(
        return_value=ExecutionResult(exit_code=0, success=True, duration_ms=1, stdout="")
    )
    await run_setup_phase(ws, secrets)

    setup_calls = [
        c for c in ws.execute.call_args_list if c.args[0] == ["bash", "/workspace/.setup/setup.sh"]
    ]
    assert len(setup_calls) == 1
    script = ws.inject_files.call_args_list[0].args[0][0][1].decode()
    return dict(setup_calls[0].kwargs["environment"] or {}), script


def _register(environment: dict[str, str]) -> OperationSpool:
    """Register `environment` exactly as AW's docker provider does at start."""
    try:
        return OperationSpool(retention_bytes=1 << 20, redact=tuple(environment.values()))
    except OperationFailure as e:
        lengths = {name: len(value) for name, value in environment.items()}
        pytest.fail(f"{e.error.kind}: {e.error.message} (registered names/lengths: {lengths})")


def _stored(spool: OperationSpool, output: bytes) -> bytes:
    spool.append(output)
    spool.finish()
    return bytes(spool._retained)  # noqa: SLF001 - the bytes an observer would page


@pytest.mark.anyio
async def test_setup_environment_with_a_github_app_identity_registers() -> None:
    environment, _ = await _setup_environment(_secrets())

    _register(environment)


@pytest.mark.anyio
async def test_the_real_secret_is_still_redacted_and_the_empty_key_ignored() -> None:
    environment, _ = await _setup_environment(_secrets(anthropic_api_key=""))

    assert environment == {ENV_CLAUDE_CODE_OAUTH_TOKEN: _FAKE_OAUTH}
    assert ENV_ANTHROPIC_API_KEY not in environment
    stored = _stored(_register(environment), f"token={_FAKE_OAUTH}\n".encode())
    assert _FAKE_OAUTH.encode() not in stored
    assert stored == b"token=[REDACTED]\n"


@pytest.mark.anyio
async def test_a_configured_api_key_is_still_registered() -> None:
    api_key = "sk-ant-api03-fake-setup-redaction-key"
    environment, _ = await _setup_environment(_secrets(anthropic_api_key=api_key))

    assert environment[ENV_ANTHROPIC_API_KEY] == api_key
    stored = _stored(_register(environment), f"{api_key} {_FAKE_OAUTH}".encode())
    assert stored == b"[REDACTED] [REDACTED]"


@pytest.mark.anyio
async def test_the_bot_identity_still_reaches_git(tmp_path: Path) -> None:
    """Moved out of the environment, not dropped: real git reads it back."""
    _, script = await _setup_environment(_secrets())
    script_path = tmp_path / "setup.sh"
    script_path.write_text(script)
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home)}

    subprocess.run(["bash", str(script_path)], env=env, check=True, capture_output=True)

    def config(key: str) -> str:
        return subprocess.run(
            ["git", "config", "--global", key], env=env, check=True, capture_output=True, text=True
        ).stdout.strip()

    assert config("user.name") == "syntropic137[bot]"
    assert config("user.email") == "123456+syntropic137[bot]@users.noreply.github.com"
