"""Whether a workspace may hold host credentials: the WorkspaceCredentialPolicy port (#1914).

A workflow cannot say "this phase needs no credential": a Scripted Agent runs
under the same ``claude`` / ``codex`` provider as a real one. So the guarantee
lives where credentials are produced, and every one of those places asks the
policy instead of deciding for itself:

- ``create_workspace``'s sidecar and token injection, and the platform grant;
- ``SetupPhaseSecrets.create`` (GitHub App tokens, Claude and Codex auth);
- ``_build_agent_env`` (the Claude credential in the agent's env);
- the session-store write token the Docker provider binds at launch.

The policy is fixed per backend at wiring (the BackendKit supplies it), never
chosen per run. See docs/research/2026-10-08-remote-executor-e2b.md, decision 5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence


class CredentialFreePhaseRefusedError(Exception):
    """A phase asked for something a credential-free workspace cannot give it.

    Raised before any workspace exists, so nothing is minted or torn down.
    """


@runtime_checkable
class WorkspaceCredentialPolicy(Protocol):
    """What a workspace may be given from the host's credentials."""

    @property
    def supplies_credentials(self) -> bool:
        """Whether host credentials reach the workspace at all."""
        ...

    def admit(self, *, phase_name: str, repositories: Sequence[str]) -> None:
        """Refuse, before ``create_workspace``, a phase this policy cannot run.

        Raises:
            CredentialFreePhaseRefusedError: the phase cannot run under this policy.
        """
        ...


class HostCredentials:
    """Today's behaviour: every configured host credential is supplied."""

    @property
    def supplies_credentials(self) -> bool:
        return True

    def admit(self, *, phase_name: str, repositories: Sequence[str]) -> None:
        del phase_name, repositories

    def __repr__(self) -> str:
        return "HostCredentials()"


class NoCredentials:
    """Nothing from the host: no sidecar, no tokens, no setup secrets, no agent auth.

    A phase with repositories is refused rather than run without them:
    ``clone_repos: false`` still hands its repositories to the setup secrets
    (#1187), so a repository always means a GitHub credential.
    """

    @property
    def supplies_credentials(self) -> bool:
        return False

    def admit(self, *, phase_name: str, repositories: Sequence[str]) -> None:
        if repositories:
            msg = (
                f"Phase '{phase_name}' names {len(repositories)} repositor"
                f"{'y' if len(repositories) == 1 else 'ies'}, and this backend runs "
                "credential-free (NoCredentials): a repository needs a GitHub credential "
                "it will not be given. Run it on a backend with HostCredentials."
            )
            raise CredentialFreePhaseRefusedError(msg)

    def __repr__(self) -> str:
        return "NoCredentials()"


HOST_CREDENTIALS: Final[WorkspaceCredentialPolicy] = HostCredentials()
NO_CREDENTIALS: Final[WorkspaceCredentialPolicy] = NoCredentials()
