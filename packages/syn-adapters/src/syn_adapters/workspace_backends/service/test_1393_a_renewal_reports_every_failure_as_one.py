"""One failure type out of a renewal, whatever went wrong inside it (#1393).

WHO READS THIS ERROR DECIDES WHY IT MATTERS. `renew_git_credential` has two
callers and they want opposite things from a failure: the startup rehearsal
refuses the phase, and the teardown quarantine logs it and pushes with the old
token anyway, because that token may still have minutes left and a commit is
riding on it. Both catch `CredentialRenewalFailedError` and nothing else.

So an exception of any OTHER type escaping this function is not a cosmetic
contract breach - it is #1393 arriving by a second door. At teardown it aborts
the quarantine before the push, which means the work is lost AND the honest
"NOT RECOVERABLE" report that the push's own result would have produced is
never written. The phase reports nothing rather than reporting a loss.

Every test here therefore drives the real `renew_git_credential`, not the
script builder underneath it: the sibling file
`test_1393_the_renewed_credential_is_the_one_git_resolves` asks what a renewal
WRITES, and this one asks what a renewal RAISES. The workspace is a double
because the shapes being reproduced are an isolation provider's failures - a
container that has gone, a docker API error, a copy that did not land - which
a real container cannot be asked to produce on demand.
"""

from __future__ import annotations

import pytest

from syn_adapters.workspace_backends.service.git_credential_renewal import (
    CredentialSource,
    renew_git_credential,
)
from syn_adapters.workspace_backends.service.setup_phase_secrets import SetupPhaseSecrets
from syn_domain.contexts.orchestration.domain.aggregate_workspace.value_objects import (
    ExecutionResult,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    CredentialRenewalFailedError,
)

pytestmark = pytest.mark.unit

_REPO = "https://github.com/org/repo-a"
_SOURCE = CredentialSource(repositories=(_REPO,), can_open_pr=False)

#: The provider-level failure every test below injects. Deliberately a bare
#: `RuntimeError`: the point is that renewal normalizes what it does not
#: recognise, and a purpose-built exception class would quietly test only the
#: ones someone had already thought of.
_PROVIDER_FAILED = "the container is gone"


def _ran(exit_code: int = 0, stderr: str = "") -> ExecutionResult:
    return ExecutionResult(
        exit_code=exit_code, success=exit_code == 0, duration_ms=1.0, stderr=stderr
    )


class _Workspace:
    """A container that takes a file and runs a script, with each step breakable.

    Stands in for `ManagedWorkspace`, whose `inject_files` and `execute` both
    reach a real container through an isolation provider and so can raise
    anything that provider raises.
    """

    workspace_id = "ws-1393"

    def __init__(
        self,
        *,
        inject_raises: bool = False,
        run_raises: bool = False,
        cleanup_raises: bool = False,
        exit_code: int = 0,
        stderr: str = "",
    ) -> None:
        self._inject_raises = inject_raises
        self._run_raises = run_raises
        self._cleanup_raises = cleanup_raises
        self._exit_code = exit_code
        self._stderr = stderr
        self.injected: list[str] = []
        self.commands: list[list[str]] = []

    async def inject_files(
        self, files: list[tuple[str, bytes]], base_path: str = "/workspace"
    ) -> None:
        if self._inject_raises:
            raise RuntimeError(_PROVIDER_FAILED)
        self.injected.extend(path for path, _ in files)

    async def execute(
        self, command: list[str], *, timeout_seconds: int | None = None
    ) -> ExecutionResult:
        self.commands.append(command)
        if command[0] == "rm":
            if self._cleanup_raises:
                raise RuntimeError(_PROVIDER_FAILED)
            return _ran()
        if self._run_raises:
            raise RuntimeError(_PROVIDER_FAILED)
        return _ran(self._exit_code, self._stderr)

    @property
    def cleaned_up(self) -> bool:
        return any(command[0] == "rm" for command in self.commands)


@pytest.fixture(autouse=True)
def _mints(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mint that always succeeds, so each test fails for its own reason.

    Renewal's first step is a live GitHub App call. Left real, every test below
    would fail at minting and prove nothing about the steps after it.
    """

    async def create(**_: object) -> SetupPhaseSecrets:
        return SetupPhaseSecrets.for_testing(
            repositories=[_REPO], repo_tokens={_REPO: "tok-renewed"}, clone_repos=False
        )

    monkeypatch.setattr(SetupPhaseSecrets, "create", create)


async def test_a_renewal_that_worked_installs_the_script_and_takes_it_away_again() -> None:
    """The control, and the one claim about the happy path worth making here.

    Without it every assertion below could pass on a function that raised
    unconditionally. The removal is asserted too because the script carries the
    token in plain text: leaving it is a secret left in the container.
    """
    workspace = _Workspace()

    await renew_git_credential(workspace, _SOURCE)

    assert workspace.injected == [".setup/renew-credential.sh"]
    assert workspace.cleaned_up


@pytest.mark.parametrize(
    ("workspace", "why"),
    [
        (_Workspace(inject_raises=True), "the script never reached the container"),
        (_Workspace(run_raises=True), "the container would not run it"),
    ],
)
async def test_a_workspace_that_will_not_take_the_script_is_a_renewal_that_failed(
    workspace: _Workspace, why: str
) -> None:
    """The blocking defect: a provider error escaping as itself.

    Before the fix `inject_files` and `execute` raised straight through this
    function. The teardown caller catches `CredentialRenewalFailedError` and
    only that, so a `RuntimeError` here aborted `_quarantine` between writing
    the commit and pushing it - the work lost and no report of the loss.
    """
    with pytest.raises(CredentialRenewalFailedError) as raised:
        await renew_git_credential(workspace, _SOURCE)

    assert _PROVIDER_FAILED in str(raised.value), why


async def test_a_script_that_exited_non_zero_is_a_renewal_that_failed() -> None:
    """The failure that was always typed, kept typed, and kept legible.

    The script's own stderr is what tells an operator whether the credential
    store was unwritable or the token was malformed, so it is carried into the
    message rather than replaced by a summary of it.
    """
    workspace = _Workspace(exit_code=3, stderr="cannot write ~/.git-credentials")

    with pytest.raises(CredentialRenewalFailedError) as raised:
        await renew_git_credential(workspace, _SOURCE)

    assert "exited 3" in str(raised.value)
    assert "cannot write ~/.git-credentials" in str(raised.value)


async def test_a_credential_that_cannot_be_minted_is_a_renewal_that_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A GitHub App outage or a revoked installation, before anything is staged.

    The one failure that happens before the container is touched, and the
    reason nothing is staged has to be visible: a renewal that minted nothing
    and injected a script anyway would be writing an empty credential over a
    working one.
    """

    async def unmintable(**_: object) -> SetupPhaseSecrets:
        raise RuntimeError("502 from api.github.com")

    monkeypatch.setattr(SetupPhaseSecrets, "create", unmintable)
    workspace = _Workspace()

    with pytest.raises(CredentialRenewalFailedError) as raised:
        await renew_git_credential(workspace, _SOURCE)

    assert "502 from api.github.com" in str(raised.value)
    assert workspace.injected == []


async def test_a_cleanup_that_failed_does_not_turn_a_good_renewal_into_a_bad_one() -> None:
    """The credential is installed; only the tidying afterwards did not happen.

    Raising here would report a usable credential as unusable - which at
    startup refuses a phase that could have saved its work, for a file it left
    in a container that is about to be destroyed. It is logged instead.
    """
    workspace = _Workspace(cleanup_raises=True)

    await renew_git_credential(workspace, _SOURCE)

    assert workspace.injected == [".setup/renew-credential.sh"]


async def test_a_cleanup_that_failed_does_not_get_to_replace_the_real_reason() -> None:
    """Masking, which is what a bare `finally` around a raising call always does.

    Two things went wrong and only one of them explains anything. An operator
    told "rm failed" about a phase whose script exited 3 is being sent to look
    at the wrong container entirely.
    """
    workspace = _Workspace(
        exit_code=3, stderr="cannot write ~/.git-credentials", cleanup_raises=True
    )

    with pytest.raises(CredentialRenewalFailedError) as raised:
        await renew_git_credential(workspace, _SOURCE)

    assert "exited 3" in str(raised.value)
    assert _PROVIDER_FAILED not in str(raised.value)
