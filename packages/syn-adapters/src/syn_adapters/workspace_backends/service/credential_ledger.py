"""Every GitHub token a workspace was handed, so each one can be taken back (#725).

MINTING NEVER REVOKES. GitHub keeps every installation token alive for its
full hour whether or not anything still holds it. A workspace that is renewed
twice during a long phase has had three live tokens issued, and tearing the
container down ends none of them. The ledger is the list teardown walks, and
it is fed by ALL THREE mint sites - the setup phase, the phase-scoped renewal,
and the quarantine renewal at teardown - because a token minted anywhere the
ledger does not see is a token nothing revokes.

RENEWAL NEVER REVOKES EITHER. A renewal swaps the file the agent's git and gh
read, but an agent command that started a second earlier may still be holding
the previous token in memory. Revoking it mid-flight would turn a routine
renewal into a failed push. The superseded token is left to expire, or to be
revoked at teardown, whichever comes first.

IN-PROCESS ONLY, AND THEREFORE BEST EFFORT ACROSS A CRASH. The ledger lives on
the `ManagedWorkspace`, which is infrastructure state (AGENTS.md: "what goes
in the event store vs. what doesn't"). If the process dies, the ledger goes
with it, and the tokens it listed live out the rest of their hour: at most 60
minutes, never longer, which is GitHub's own ceiling. Persisting raw tokens so
that a restart could revoke them would be a far worse trade than that.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Sequence

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class IssuedToken:
    """One installation token, as it was issued to one workspace."""

    token: str = field(repr=False)
    installation_id: str
    repositories: tuple[str, ...]
    """``owner/repo`` names the token reaches. Empty for the installation-wide
    token a repo-less workflow's gh is given."""
    expires_at: datetime

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


@dataclass(frozen=True)
class Revocation:
    """What a teardown revocation did, so it can be asserted on and logged."""

    revoked: tuple[IssuedToken, ...]
    failed: tuple[IssuedToken, ...]


@dataclass
class CredentialLedger:
    """The tokens one workspace was issued, and which of them are installed."""

    _issued: list[IssuedToken] = field(default_factory=list)
    _installed: tuple[IssuedToken, ...] = ()

    def record(self, tokens: Iterable[IssuedToken]) -> None:
        """Remember tokens the moment they are minted.

        BEFORE they are installed, not after: a token whose installation then
        fails is still live at GitHub, and is exactly the one nothing else
        would remember to revoke.
        """
        self._issued.extend(tokens)

    def mark_installed(self, tokens: Sequence[IssuedToken]) -> None:
        """These are the tokens the workspace's git and gh now resolve."""
        self._installed = tuple(tokens)

    @property
    def issued(self) -> tuple[IssuedToken, ...]:
        return tuple(self._issued)

    @property
    def expires_at(self) -> datetime | None:
        """When the credential the workspace currently holds stops working.

        The EARLIEST expiry of the installed batch: a multi-installation
        workspace holds one token per installation, and it is as usable as
        the first of them to die. None when nothing is installed.
        """
        return min((token.expires_at for token in self._installed), default=None)

    async def revoke_unexpired(
        self,
        revoke: Callable[[str], Awaitable[None]],
        *,
        now: datetime | None = None,
    ) -> Revocation:
        """Revoke every token that is still live, and forget all of them.

        Never raises. It runs at teardown, after the quarantine push, and a
        revocation that fails must not become the reason a workspace is not
        cleaned up; the token still dies on its own within the hour. Each
        failure is logged with enough to find the token in GitHub's audit log
        (installation and repos), and never the token itself.
        """
        at = now if now is not None else datetime.now(UTC)
        revoked: list[IssuedToken] = []
        failed: list[IssuedToken] = []
        for issued in self._issued:
            if issued.is_expired(at):
                continue
            try:
                await revoke(issued.token)
            except Exception:
                logger.warning(
                    "Could not revoke an installation token (installation=%s, repos=%s, "
                    "expires_at=%s); it stays live until it expires",
                    issued.installation_id,
                    list(issued.repositories) or "all",
                    issued.expires_at.isoformat(),
                    exc_info=True,
                )
                failed.append(issued)
            else:
                revoked.append(issued)
        self._issued.clear()
        self._installed = ()
        return Revocation(revoked=tuple(revoked), failed=tuple(failed))


async def revoke_with_github_app(token: str) -> None:
    """Revoke one token through the configured GitHub App's HTTP client.

    The request is authenticated with the token itself, so the App's private
    key is never used; the client is only the transport and base URL.
    """
    from syn_adapters.github import GitHubAppClient
    from syn_shared.settings.github import GitHubAppSettings

    async with GitHubAppClient(GitHubAppSettings()) as client:
        await client.revoke_token(token)
