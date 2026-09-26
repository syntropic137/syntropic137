"""A workspace's GitHub credential, from the first mint to the last revocation (#725).

Four claims, each asserted on what a consumer reads rather than on the object
that was edited:

- A TOKEN REACHES ONLY THE REPOSITORIES ITS WORKSPACE WAS GIVEN. Asked of a
  fake GitHub that grants what the request says and nothing more - the
  behaviour of the real endpoint, and the only reason naming repositories in
  the request matters.
- ``gh`` READS hosts.yml, ROUTED BY THE REPO UNDER WORK (#1129), before and
  after a renewal. Asked of the file the real setup and renewal scripts leave
  in a HOME, under real bash, because a script that contains the right token
  and leaves the wrong one in place is the bug.
- EVERY MINT IS IN THE LEDGER: setup, the renewal task, and both quarantine
  paths, which are the domain's own functions driven against a real
  ``ManagedWorkspace``.
- TEARDOWN REVOKES WHAT IS STILL LIVE, after the caller's block (and so after
  the quarantine push), and a revocation that fails does not stop the rest.

The workspace's container is a temporary directory: ``/workspace`` in paths
and scripts is rewritten into it, and HOME is a directory beside it.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import httpx
import pytest

from syn_adapters.github.agent_token import mint_agent_token
from syn_adapters.github.client import GitHubAppError
from syn_adapters.github.client_token import TokenRequest, revoke_installation_token
from syn_adapters.workspace_backends.service import setup_phase_secrets
from syn_adapters.workspace_backends.service.credential_keeper import (
    FIRST_RENEWAL,
    keep_credential_fresh,
)
from syn_adapters.workspace_backends.service.issued_tokens import IssuedToken
from syn_adapters.workspace_backends.service.managed_workspace import ManagedWorkspace
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow import (
    quarantine_rehearsal,
    unpushed_work_guard,
)

if TYPE_CHECKING:
    from syn_adapters.github.client import GitHubAppClient, InstallationToken
    from syn_adapters.workspace_backends.service.credential_keeper import CredentialLapse
    from syn_adapters.workspace_backends.service.workspace_service import WorkspaceService

pytestmark = pytest.mark.unit

_GRANTED = {"contents": "write", "pull_requests": "write", "metadata": "read"}

#: Two repositories in one installation, and one in another.
_OWNERS = {
    "org/repo-a": "inst-1",
    "org/repo-b": "inst-1",
    "other/repo-x": "inst-2",
}
_A = "https://github.com/org/repo-a"
_X = "https://github.com/other/repo-x"


class _GitHub:
    """GitHub, as far as these hops can see it.

    Installations own repositories, and a token reaches exactly what it was
    minted for: the named repositories, or - with none named - everything its
    installation covers. That second rule is the behaviour #725 is about.
    """

    def __init__(self) -> None:
        self.token_requests: list[tuple[str, TokenRequest | None]] = []
        self.revoked: list[str] = []
        self.refuse_to_revoke: set[str] = set()
        #: Installations whose token request GitHub answers 500.
        self.refuse_to_mint: set[str] = set()
        self.clients_opened = 0
        self.clients_closed = 0
        self._reach: dict[str, frozenset[str]] = {}

    def reaches(self, token: str | None, full_name: str) -> bool:
        if token is None or token in self.revoked:
            return False
        return full_name in self._reach.get(token, frozenset())

    @property
    def minted(self) -> list[str]:
        return list(self._reach)

    async def get(self, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
        return httpx.Response(
            200, json={"permissions": _GRANTED}, request=httpx.Request("GET", path)
        )

    async def post(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        json: dict[str, dict[str, str] | list[str]] | None = None,
    ) -> httpx.Response:
        installation = path.split("/")[3]
        request = None if json is None else TokenRequest.model_validate(json)
        self.token_requests.append((installation, request))
        if installation in self.refuse_to_mint:
            return httpx.Response(500, request=httpx.Request("POST", path))
        covered = {name for name, owner in _OWNERS.items() if owner == installation}
        if request is not None and request.repositories is not None:
            covered = {name for name in covered if name.split("/")[1] in request.repositories}
        token = f"ghs_{installation}_{len(self._reach) + 1}"
        self._reach[token] = frozenset(covered)
        expires = datetime.now(UTC) + timedelta(hours=1)
        return httpx.Response(
            201,
            json={
                "token": token,
                "expires_at": expires.isoformat().replace("+00:00", "Z"),
                "permissions": _GRANTED,
                "repository_selection": "selected",
            },
            request=httpx.Request("POST", path),
        )

    async def delete(self, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
        token = (headers or {}).get("Authorization", "").removeprefix("token ")
        if token in self.refuse_to_revoke:
            return httpx.Response(500, request=httpx.Request("DELETE", path))
        self.revoked.append(token)
        return httpx.Response(204, request=httpx.Request("DELETE", path))


class _AppClient:
    """GitHubAppClient's surface, with the REAL token code behind it."""

    def __init__(self, github: _GitHub) -> None:
        self._http = github
        self._cached_tokens: dict[str, InstallationToken] = {}
        github.clients_opened += 1

    def _generate_jwt(self) -> str:
        return "jwt-for-tests"

    async def __aenter__(self) -> _AppClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get_installation_for_repo(self, full_name: str) -> str:
        if full_name not in _OWNERS:
            raise GitHubAppError(f"no installation owns {full_name}")
        return _OWNERS[full_name]

    async def list_installations(self) -> list[dict[str, str]]:
        return [{"id": owner} for owner in dict.fromkeys(_OWNERS.values())]

    async def mint_agent_token(
        self, installation_id: str, *, can_open_pr: bool, repositories: list[str] | None = None
    ) -> InstallationToken:
        return await mint_agent_token(
            cast("GitHubAppClient", self),
            installation_id,
            can_open_pr=can_open_pr,
            repositories=repositories,
        )

    async def revoke_installation_token(self, token: str) -> None:
        await revoke_installation_token(cast("GitHubAppClient", self), token)

    async def close(self) -> None:
        self._http.clients_closed += 1


@dataclass(frozen=True)
class _Settings:
    is_configured: bool = True
    bot_name: str = "syn-bot"
    bot_email: str = "bot@example.com"


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> _GitHub:
    """A configured GitHub App whose every client talks to one fake GitHub."""
    fake = _GitHub()
    monkeypatch.setattr("syn_adapters.github.GitHubAppClient", lambda *_a, **_k: _AppClient(fake))
    monkeypatch.setattr("syn_shared.settings.github.GitHubAppSettings", lambda: _Settings())
    monkeypatch.setattr(setup_phase_secrets, "_resolve_claude_credentials", lambda: (None, None))
    return fake


class _Container:
    """An isolation provider whose container is a temporary directory."""

    def __init__(self, root: Path) -> None:
        self.home = root / "home"
        self.workspace = root / "workspace"
        self.home.mkdir(parents=True)
        self.workspace.mkdir(parents=True)

    def _local(self, text: str) -> str:
        return text.replace("/workspace", str(self.workspace))

    async def copy_to(
        self, _handle: object, files: list[tuple[str, bytes]], base_path: str = "/workspace"
    ) -> None:
        for relative, content in files:
            path = Path(self._local(base_path)) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._local(content.decode()))

    async def execute(
        self,
        _handle: object,
        command: list[str],
        *,
        timeout_seconds: int | None = None,
        working_directory: str | None = None,
        environment: dict[str, str] | None = None,
    ) -> ExecutionResult:
        del timeout_seconds, working_directory
        proc = subprocess.run(
            [self._local(arg) for arg in command],
            env={**(environment or {}), **self._env},
            capture_output=True,
            text=True,
            check=False,
        )
        return ExecutionResult(
            exit_code=proc.returncode,
            success=proc.returncode == 0,
            duration_ms=1.0,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    @property
    def _env(self) -> dict[str, str]:
        return {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/bin/false",
        }

    def gh_token(self) -> str | None:
        """The token `gh` authenticates with: the one in hosts.yml."""
        hosts = self.home / ".config" / "gh" / "hosts.yml"
        if not hosts.exists():
            return None
        for line in hosts.read_text().splitlines():
            if "oauth_token:" in line:
                return line.split("oauth_token:", 1)[1].strip()
        return None

    def git_token(self, full_name: str) -> str | None:
        """What `git credential fill` answers for a push to ``full_name``."""
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input=f"protocol=https\nhost=github.com\npath={full_name}\n\n",
            env=self._env,
            capture_output=True,
            text=True,
            check=False,
        )
        for line in proc.stdout.splitlines():
            if line.startswith("password="):
                return line.removeprefix("password=")
        return None


class _Service:
    def __init__(self, container: _Container) -> None:
        self._isolation = container


def _workspace(container: _Container) -> ManagedWorkspace:
    return ManagedWorkspace(
        workspace_id="ws-725",
        execution_id="exec-725",
        aggregate=MagicMock(),
        isolation_handle=MagicMock(),
        sidecar_handle=None,
        _service=cast("WorkspaceService", _Service(container)),
    )


async def _provisioned(tmp_path: Path, repos: list[str]) -> tuple[ManagedWorkspace, _Container]:
    """A workspace whose setup phase ran for ``repos``, the way provisioning runs it."""
    container = _Container(tmp_path)
    workspace = _workspace(container)
    secrets = await SetupPhaseSecrets.create(
        repositories=repos, clone_repos=False, require_github=bool(repos)
    )
    result = await workspace.run_setup_phase(secrets)
    assert result.exit_code == 0, result.stderr
    return workspace, container


class TestATokenReachesOnlyItsWorkspacesRepositories:
    async def test_a_token_for_repo_a_cannot_be_used_for_repo_b(
        self, github: _GitHub, tmp_path: Path
    ) -> None:
        """Same installation, so the token used to reach both."""
        _, container = await _provisioned(tmp_path, [_A])

        token = container.git_token("org/repo-a")
        assert github.reaches(token, "org/repo-a")
        assert not github.reaches(token, "org/repo-b")

    async def test_the_request_names_the_repositories_by_name_only(
        self, github: _GitHub, tmp_path: Path
    ) -> None:
        await _provisioned(tmp_path, [_A])

        ((installation, request),) = github.token_requests
        assert installation == "inst-1"
        assert request is not None
        assert request.repositories == ["repo-a"]


class TestGhReadsHostsYmlRoutedByTheRepoUnderWork:
    async def test_two_installations_gh_gets_the_primary_repos(
        self, github: _GitHub, tmp_path: Path
    ) -> None:
        _, container = await _provisioned(tmp_path, [_A, _X])

        assert github.reaches(container.gh_token(), "org/repo-a")
        # git still reaches both, each through its own installation's token.
        assert github.reaches(container.git_token("org/repo-a"), "org/repo-a")
        assert github.reaches(container.git_token("other/repo-x"), "other/repo-x")

    async def test_the_primary_repo_decides_not_the_installation_order(
        self, github: _GitHub, tmp_path: Path
    ) -> None:
        _, container = await _provisioned(tmp_path, [_X, _A])

        assert github.reaches(container.gh_token(), "other/repo-x")
        assert not github.reaches(container.gh_token(), "org/repo-a"), (
            "cross-installation gh is out of scope (#725): one credential, the primary repo's"
        )

    async def test_a_repo_less_workflow_gets_the_first_installations_gh(
        self, github: _GitHub, tmp_path: Path
    ) -> None:
        _, container = await _provisioned(tmp_path, [])

        ((installation, request),) = github.token_requests
        assert installation == "inst-1"
        assert request is not None
        assert request.repositories is None, (
            "a repo-less credential has no repository to be scoped to"
        )
        assert github.reaches(container.gh_token(), "org/repo-a")
        assert container.git_token("org/repo-a") is None

    @pytest.mark.parametrize(
        ("repos", "primary"),
        [([_A, _X], "org/repo-a"), ([_X, _A], "other/repo-x"), ([], "org/repo-a")],
        ids=["a-then-x", "x-then-a", "repo-less"],
    )
    async def test_a_renewal_replaces_gh_credential_with_one_routed_the_same_way(
        self, github: _GitHub, tmp_path: Path, repos: list[str], primary: str
    ) -> None:
        workspace, container = await _provisioned(tmp_path, repos)
        before = container.gh_token()

        await workspace.renew_git_credential()

        after = container.gh_token()
        assert after != before
        assert github.reaches(after, primary)


class TestTheLedgerCoversEveryMintSite:
    async def test_setup_the_renewal_task_and_both_quarantine_paths(
        self, github: _GitHub, tmp_path: Path
    ) -> None:
        workspace, _ = await _provisioned(tmp_path, [_A, _X])
        after_setup = len(workspace.issued_tokens)

        await _one_scheduled_renewal(workspace)
        after_task = len(workspace.issued_tokens)

        await quarantine_rehearsal._renew_credential(
            workspace, phase_id="p", attempts=1, retry_seconds=0
        )
        after_rehearsal = len(workspace.issued_tokens)

        await unpushed_work_guard._renew_credential(workspace, doing="quarantine push")
        after_teardown = len(workspace.issued_tokens)

        # Two installations, so two tokens per mint.
        assert [after_setup, after_task, after_rehearsal, after_teardown] == [2, 4, 6, 8]
        assert [t.token for t in workspace.issued_tokens] == github.minted

    async def test_each_entry_says_what_it_was_issued_for(
        self, github: _GitHub, tmp_path: Path
    ) -> None:
        workspace, _ = await _provisioned(tmp_path, [_A, _X])

        assert {(t.installation_id, t.repositories) for t in workspace.issued_tokens} == {
            ("inst-1", ("org/repo-a",)),
            ("inst-2", ("other/repo-x",)),
        }
        assert all(t.expires_at > datetime.now(UTC) for t in workspace.issued_tokens)

    async def test_the_installed_credentials_expiry_is_the_newest_batchs(
        self, github: _GitHub, tmp_path: Path
    ) -> None:
        workspace, _ = await _provisioned(tmp_path, [_A])
        first = workspace.credential_expires_at

        (renewed,) = await workspace.renew_git_credential()

        assert first is not None
        assert workspace.credential_expires_at == renewed.expires_at

    async def test_the_token_never_appears_in_the_ledgers_repr(
        self, github: _GitHub, tmp_path: Path
    ) -> None:
        workspace, _ = await _provisioned(tmp_path, [_A])

        (issued,) = workspace.issued_tokens
        assert issued.token not in repr(issued)


async def _one_scheduled_renewal(workspace: ManagedWorkspace) -> None:
    """Let the real renewal task run once, on a clock that skips the forty minutes."""
    parked = asyncio.Event()
    slept: list[timedelta] = []

    async def sleep(delay: timedelta) -> None:
        slept.append(delay)
        if len(slept) > 1:
            parked.set()
            await asyncio.Future()

    async def on_lapse(_lapse: CredentialLapse) -> None:
        raise AssertionError("the renewal was expected to succeed")

    async with keep_credential_fresh(workspace, on_lapse=on_lapse, sleep=sleep):
        await asyncio.wait_for(parked.wait(), timeout=10)
    assert slept[0] == FIRST_RENEWAL


class TestTeardownRevokesWhatIsStillLive:
    async def test_every_unexpired_token_is_revoked(self, github: _GitHub, tmp_path: Path) -> None:
        workspace, _ = await _provisioned(tmp_path, [_A, _X])
        await workspace.renew_git_credential()

        await workspace.revoke_issued_credentials()

        assert sorted(github.revoked) == sorted(github.minted)

    async def test_a_failed_revocation_does_not_stop_the_rest(
        self, github: _GitHub, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        workspace, _ = await _provisioned(tmp_path, [_A, _X])
        await workspace.renew_git_credential()
        stuck = github.minted[0]
        github.refuse_to_revoke.add(stuck)

        await workspace.revoke_issued_credentials()

        assert sorted(github.revoked) == sorted(set(github.minted) - {stuck})
        assert "Could not revoke an installation token" in caplog.text
        assert stuck not in caplog.text, "the log must not carry the credential"

    async def test_an_expired_token_is_not_presented_again(self, github: _GitHub) -> None:
        from syn_adapters.workspace_backends.service.issued_tokens import IssuanceLedger

        now = datetime.now(UTC)
        ledger = IssuanceLedger()
        ledger.record(
            [
                IssuedToken("ghs_old", "inst-1", ("org/repo-a",), now - timedelta(minutes=1)),
                IssuedToken("ghs_live", "inst-1", ("org/repo-a",), now + timedelta(minutes=1)),
            ]
        )

        await ledger.revoke_unexpired(_AppClient(github).revoke_installation_token, now=now)

        assert github.revoked == ["ghs_live"]

    async def test_workspace_service_revokes_after_the_callers_block_on_every_exit(
        self, github: _GitHub, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After the block - which is where the quarantine push runs - and on error too."""
        from syn_adapters.workspace_backends.service import WorkspaceBackend, WorkspaceService

        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        service = WorkspaceService.create(backend=WorkspaceBackend.MEMORY)
        secrets = await SetupPhaseSecrets.create(repositories=[_A], clone_repos=False)
        revoked_inside: list[str] = []

        with pytest.raises(RuntimeError, match="the phase failed"):
            async with service.create_workspace(execution_id="exec-725") as workspace:
                await workspace.run_setup_phase(secrets)
                revoked_inside.extend(github.revoked)
                raise RuntimeError("the phase failed")

        assert revoked_inside == []
        assert github.revoked == github.minted


class TestAFailedBatchLeavesNothingLive:
    """A mint that fails part-way must not strand the tokens it already minted.

    `SetupPhaseSecrets.create` raises, so its tokens never reach a container
    or a workspace ledger; if it does not revoke them, nothing ever will, and
    each stays live for its full hour (codex review of #1448).
    """

    async def test_a_partial_mint_revokes_what_it_already_minted(self, github: _GitHub) -> None:
        github.refuse_to_mint = {"inst-2"}

        with pytest.raises(GitHubAppError):
            await SetupPhaseSecrets.create(
                repositories=[_A, _X], clone_repos=False, require_github=True
            )

        (orphan,) = github.minted
        assert orphan.startswith("ghs_inst-1_")
        assert orphan in github.revoked

    async def test_a_failed_revocation_still_raises_the_mint_failure(self, github: _GitHub) -> None:
        github.refuse_to_mint = {"inst-2"}
        github.refuse_to_revoke = {"ghs_inst-1_1"}

        with pytest.raises(GitHubAppError):
            await SetupPhaseSecrets.create(
                repositories=[_A, _X], clone_repos=False, require_github=True
            )

        assert github.revoked == []

    async def test_a_complete_batch_revokes_nothing(self, github: _GitHub) -> None:
        await SetupPhaseSecrets.create(
            repositories=[_A, _X], clone_repos=False, require_github=True
        )

        assert len(github.minted) == 2
        assert github.revoked == []


class TestEveryClientIsClosed:
    """A renewal builds a client every 40 minutes; each owns a connection pool."""

    async def test_after_a_successful_mint(self, github: _GitHub) -> None:
        await SetupPhaseSecrets.create(repositories=[_A], clone_repos=False, require_github=True)

        assert github.clients_opened == 1
        assert github.clients_closed == 1

    async def test_after_a_failed_mint(self, github: _GitHub) -> None:
        github.refuse_to_mint = {"inst-1"}

        with pytest.raises(GitHubAppError):
            await SetupPhaseSecrets.create(
                repositories=[_A], clone_repos=False, require_github=True
            )

        assert github.clients_opened == github.clients_closed == 1

    async def test_across_repeated_renewals(self, github: _GitHub, tmp_path: Path) -> None:
        workspace, _ = await _provisioned(tmp_path, [_A])

        for _ in range(3):
            await workspace.renew_git_credential()

        assert github.clients_opened == github.clients_closed == 4
