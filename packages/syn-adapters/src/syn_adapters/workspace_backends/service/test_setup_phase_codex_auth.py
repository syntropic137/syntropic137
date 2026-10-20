"""Codex authentication tests for the ADR-024 setup phase."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_adapters.workspace_backends.service.issued_tokens import IssuanceLedger
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_adapters.workspace_backends.service.setup_phase import (
    _build_setup_env,
    clear_secrets,
    run_setup_phase,
)
from syn_adapters.workspace_backends.service.setup_phase_secrets import (
    SetupPhaseSecrets,
    _resolve_codex_credentials,
)
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def _workspace() -> MagicMock:
    workspace = MagicMock(spec=ManagedWorkspace)
    workspace.workspace_id = "workspace-codex-auth"
    workspace.inject_files = AsyncMock()
    workspace.execute = AsyncMock()
    return workspace


def _execute_side_effect(default_exit: int = 0, *, staged_present: bool = False):
    """AsyncMock side_effect for ws.execute.

    The staged-credential probe now answers on STDOUT and always exits 0, so a
    nonzero status means the PROBE failed rather than that the file is gone.
    This double reported the old protocol - exit 1, empty stdout - which the
    guard would now read as UNVERIFIABLE and refuse. Updated rather than
    loosened: a shared double that lies about the contract is how a guard gets
    certified while broken, which is exactly what happened here.

    Reports the credential GONE by default (the setup script relocated and
    removed it); pass ``staged_present=True`` to simulate a cleanup that could
    not remove it.
    """

    def _run(cmd: list[str], **_kwargs: object) -> ExecutionResult:
        joined = " ".join(cmd)
        if "codex-auth.json" in joined and "STAGED_CREDENTIAL" in joined:
            marker = "STAGED_CREDENTIAL_PRESENT" if staged_present else "STAGED_CREDENTIAL_ABSENT"
            return ExecutionResult(
                exit_code=0, success=True, duration_ms=1, stdout=marker, stderr=""
            )
        if "codex-auth.json" in joined and joined.startswith("rm "):
            # Removal itself succeeds. `staged_present` models a credential
            # that survives it, which is what the recheck then catches - not a
            # container where `rm` cannot run.
            return ExecutionResult(exit_code=0, success=True, duration_ms=1, stdout="", stderr="")
        exit_code = default_exit
        return ExecutionResult(
            exit_code=exit_code,
            success=exit_code == 0,
            duration_ms=1,
            stdout="",
            stderr="",
        )

    return _run


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
            ledger=IssuanceLedger(), require_github=False, include_codex_auth=False
        )
        codex_secrets = await SetupPhaseSecrets.create(
            ledger=IssuanceLedger(), require_github=False, include_codex_auth=True
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
    workspace.execute = AsyncMock(side_effect=_execute_side_effect(0))
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
    # The SETUP SCRIPT fails; the staged-credential cleanup still works. A
    # blanket "every command returns 7" also made the credential removal fail,
    # which now raises fail-closed and is a different scenario from the one
    # this test is about.
    workspace.execute.side_effect = _execute_side_effect(default_exit=7)
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
    workspace.execute = AsyncMock(side_effect=_execute_side_effect(0))
    secrets = SetupPhaseSecrets.for_testing(codex_auth_json='{"a":1}')
    cleanup = AsyncMock()

    with (
        patch(
            "syn_adapters.workspace_backends.service.setup_phase.clear_secrets",
            new=cleanup,
        ),
        pytest.raises(RuntimeError, match="inject boom"),
    ):
        await run_setup_phase(workspace, secrets)

    cleanup.assert_awaited_once_with(workspace)


@pytest.mark.unit
@pytest.mark.anyio
async def test_lingering_codex_credential_fails_closed() -> None:
    # If cleanup cannot remove the staged codex credential, run_setup_phase must
    # FAIL CLOSED (raise) rather than silently report the secret as cleared.
    workspace = _workspace()
    workspace.execute = AsyncMock(side_effect=_execute_side_effect(0, staged_present=True))
    secrets = SetupPhaseSecrets.for_testing(codex_auth_json='{"a":1}')

    with (
        patch(
            "syn_adapters.workspace_backends.service.setup_phase.clear_secrets",
            new=AsyncMock(),
        ),
        # Wording changed with the fail-closed rework: removal now has its own
        # error ("unable to remove"), and this is the case where removal
        # reported success but the credential is still visible afterwards.
        pytest.raises(RuntimeError, match="unable to confirm removal"),
    ):
        await run_setup_phase(workspace, secrets)


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


# ---------------------------------------------------------------------------
# OPENAI_API_KEY fallback (#1971)
# ---------------------------------------------------------------------------

_FAKE_KEY = "sk-proj-fake-openai-key-1971"
_CHATGPT_AUTH = '{"auth_mode":"chatgpt","tokens":{"access_token":"a","refresh_token":"r"}}'


@pytest.fixture
def codex_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str, str], None]]:
    """Set CODEX_AUTH_JSON and OPENAI_API_KEY ("" = unset) and reload settings."""
    from syn_shared.env_constants import ENV_CODEX_AUTH_JSON, ENV_OPENAI_API_KEY
    from syn_shared.settings import reset_settings

    def apply(codex_auth_json: str, openai_api_key: str) -> None:
        monkeypatch.setenv(ENV_CODEX_AUTH_JSON, codex_auth_json)
        monkeypatch.setenv(ENV_OPENAI_API_KEY, openai_api_key)
        reset_settings()

    yield apply
    reset_settings()


@pytest.mark.unit
def test_auth_json_only_is_staged_verbatim(codex_settings: Callable[[str, str], None]) -> None:
    codex_settings(_CHATGPT_AUTH, "")
    assert _resolve_codex_credentials() == _CHATGPT_AUTH


@pytest.mark.unit
def test_key_only_is_staged_as_codex_api_key_auth_json(
    codex_settings: Callable[[str, str], None],
) -> None:
    codex_settings("", _FAKE_KEY)
    resolved = _resolve_codex_credentials()
    assert resolved is not None
    assert json.loads(resolved) == {"auth_mode": "apikey", "OPENAI_API_KEY": _FAKE_KEY}


@pytest.mark.unit
def test_both_set_auth_json_wins_with_a_warning(
    codex_settings: Callable[[str, str], None], caplog: pytest.LogCaptureFixture
) -> None:
    codex_settings(_CHATGPT_AUTH, _FAKE_KEY)
    with caplog.at_level(logging.WARNING):
        resolved = _resolve_codex_credentials()
    assert resolved == _CHATGPT_AUTH
    assert any(
        "CODEX_AUTH_JSON" in r.getMessage() and "OPENAI_API_KEY" in r.getMessage()
        for r in caplog.records
    )
    # Hazard: the warning names the settings, never the value.
    assert all(_FAKE_KEY not in r.getMessage() for r in caplog.records)


@pytest.mark.unit
def test_neither_set_stages_nothing(codex_settings: Callable[[str, str], None]) -> None:
    codex_settings("", "")
    assert _resolve_codex_credentials() is None


@pytest.mark.unit
@pytest.mark.anyio
async def test_key_never_reaches_script_env_or_logs(
    codex_settings: Callable[[str, str], None], caplog: pytest.LogCaptureFixture
) -> None:
    """The hazard itself: a real key-only config, run through the real setup path.

    The key must arrive ONLY as the bytes of the staged auth file, never in the
    setup script text, the setup env, or any log line.
    """
    codex_settings("", _FAKE_KEY)
    secrets = await SetupPhaseSecrets.create(
        ledger=IssuanceLedger(), require_github=False, include_codex_auth=True
    )
    workspace = _workspace()
    workspace.execute = AsyncMock(side_effect=_execute_side_effect(0))

    with (
        caplog.at_level(logging.DEBUG),
        patch(
            "syn_adapters.workspace_backends.service.setup_phase.clear_secrets",
            new=AsyncMock(),
        ),
    ):
        await run_setup_phase(workspace, secrets)

    script = secrets.build_setup_script()
    assert _FAKE_KEY not in script
    assert "install -m 600 /workspace/.setup/codex-auth.json ~/.codex/auth.json" in script
    assert all(_FAKE_KEY not in value for value in _build_setup_env(secrets).values())
    assert all(_FAKE_KEY not in r.getMessage() for r in caplog.records)

    staged = [
        files
        for call in workspace.inject_files.await_args_list
        for files in call.args
        if any(path == ".setup/codex-auth.json" for path, _ in files)
    ]
    assert staged, "the key-only credential was never staged as the codex auth file"
    for files in staged:
        for path, contents in files:
            if path == ".setup/codex-auth.json":
                assert json.loads(contents) == {"auth_mode": "apikey", "OPENAI_API_KEY": _FAKE_KEY}
            else:
                assert _FAKE_KEY.encode() not in contents
    # Every exec argv the setup ran: the key is never on a command line.
    for call in workspace.execute.await_args_list:
        assert all(_FAKE_KEY not in str(arg) for arg in call.args[0])
        environment = call.kwargs.get("environment") or {}
        assert all(_FAKE_KEY not in value for value in environment.values())


@pytest.mark.unit
@pytest.mark.anyio
async def test_key_only_is_scoped_to_codex_phases(
    codex_settings: Callable[[str, str], None],
) -> None:
    codex_settings("", _FAKE_KEY)
    claude_secrets = await SetupPhaseSecrets.create(
        ledger=IssuanceLedger(), require_github=False, include_codex_auth=False
    )
    assert claude_secrets.codex_auth_json is None
    assert _FAKE_KEY not in claude_secrets.build_setup_script()


# An underscore and hyphens in the body: the shape a partial redaction cut short.
_FAKE_PROJECT_KEY = "sk-proj-FAKEfake0000_tail1111-tail2222"


def _key_fragments(key: str) -> list[str]:
    body = key.removeprefix("sk-")
    return [key, body, *(p for p in body.replace("_", "-").split("-") if len(p) >= 4)]


@pytest.mark.unit
@pytest.mark.anyio
async def test_a_failing_setup_that_echoes_the_key_logs_and_returns_none_of_it(
    codex_settings: Callable[[str, str], None], caplog: pytest.LogCaptureFixture
) -> None:
    """The hazard the review found: setup stderr carrying the key, verbatim.

    A script that echoes its staged auth file (or a shell trace) puts the key on
    stderr. That output is logged here and returned to the caller, which quotes
    it into the failure an execution records. No fragment may survive either.
    """
    codex_settings("", _FAKE_PROJECT_KEY)
    secrets = await SetupPhaseSecrets.create(
        ledger=IssuanceLedger(), require_github=False, include_codex_auth=True
    )
    leaked = f'cat: {{"auth_mode":"apikey","OPENAI_API_KEY":"{_FAKE_PROJECT_KEY}"}}\n'
    probe = _execute_side_effect(0)

    def _run(cmd: list[str], **kwargs: object) -> ExecutionResult:
        if cmd == ["bash", "/workspace/.setup/setup.sh"]:
            return ExecutionResult(
                exit_code=1,
                success=False,
                duration_ms=1,
                stdout=f"echo {_FAKE_PROJECT_KEY}",
                stderr=leaked + f"token {_FAKE_PROJECT_KEY}",
            )
        return probe(cmd, **kwargs)

    workspace = _workspace()
    workspace.execute = AsyncMock(side_effect=_run)
    with (
        caplog.at_level(logging.DEBUG),
        patch(
            "syn_adapters.workspace_backends.service.setup_phase.clear_secrets",
            new=AsyncMock(),
        ),
    ):
        result = await run_setup_phase(workspace, secrets)

    assert result.exit_code == 1
    assert "Secret-injection setup failed" in caplog.text
    for fragment in _key_fragments(_FAKE_PROJECT_KEY):
        assert fragment not in caplog.text, fragment
        assert all(fragment not in r.getMessage() for r in caplog.records), fragment
        assert fragment not in result.stderr, fragment
        assert fragment not in result.stdout, fragment
