"""Every GitHub token a workspace was ever handed, so it can be renewed and revoked (#725).

A WORKSPACE'S CREDENTIAL IS NOT ONE TOKEN, it is a succession of them. The
setup phase mints one per installation, the renewal task mints another every
forty minutes while the agent runs, and the quarantine rehearsal and the
teardown push each mint again before they depend on it. GitHub installation
tokens live exactly one hour, and minting a new one does not end an old one:
each stays usable for its full hour unless it is revoked, and only the token
itself can authenticate its own revocation (``DELETE /installation/token``).

So a workspace that does not keep what it issued cannot answer either
question that matters about its credential:

- WHEN DOES THE ONE IN THE CONTAINER DIE - which the renewal task needs, to
  know how long it may keep retrying before the phase is holding nothing.
- WHAT IS STILL LIVE WHEN THE WORKSPACE GOES - which teardown needs, to end
  tokens the destroyed container can no longer use but anyone who copied one
  out of it still could.

IN-PROCESS AND BEST EFFORT. The ledger is memory in the process that
provisioned the workspace, deliberately: the tokens themselves are secrets and
do not belong in the event store, and the workspace they were issued to is
infrastructure-ephemeral under the crash model in AGENTS.md - after a crash
the container is assumed lost, and so is this. A token issued before a crash
is not revoked by anyone; it expires on GitHub's own clock, at most an hour
later. That is the same exposure every token had before this ledger existed,
and it is bounded; closing it would take the per-workspace credential sidecar
tracked as Tier 1 of #725.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IssuedToken:
    """One installation token, and what it was issued for."""

    token: str = field(repr=False)
    """The secret itself. Kept because revoking a token requires presenting
    it; excluded from ``repr`` so a log line or a failed assertion that prints
    the ledger cannot print the credential."""
    installation_id: str
    repositories: tuple[str, ...]
    """``owner/repo`` for every repository the token reaches. Empty for a
    token that was not repository-scoped - a repo-less workflow's gh
    credential - which reaches whatever the installation covers."""
    expires_at: datetime


@dataclass
class IssuanceLedger:
    """What a workspace was issued, and which of it is the credential installed now.

    Two facts, kept apart on purpose. A token is ``record``-ed the moment it
    is minted, whether or not it ever reaches the container: a renewal that
    minted and then failed to install still created a live token, and it is
    still teardown's to revoke. A batch becomes the ``installed`` one only
    once the container holds it, because that is the only batch whose expiry
    says anything about the credential the agent is using.
    """

    _issued: list[IssuedToken] = field(default_factory=list)
    _installed: tuple[IssuedToken, ...] = ()

    def record(self, tokens: Iterable[IssuedToken]) -> None:
        """Remember newly minted tokens, installed or not."""
        self._issued.extend(tokens)

    def installed(self, tokens: tuple[IssuedToken, ...]) -> None:
        """Mark ``tokens`` as the credential the container now holds."""
        if tokens:
            self._installed = tokens

    @property
    def issued(self) -> tuple[IssuedToken, ...]:
        """Every token recorded, oldest first."""
        return tuple(self._issued)

    @property
    def credential_expires_at(self) -> datetime | None:
        """When the credential in the container stops working, or None if it holds none.

        The EARLIEST expiry of the installed batch: a workspace spanning two
        installations holds two tokens, and it is broken as soon as either
        one is.
        """
        if not self._installed:
            return None
        return min(token.expires_at for token in self._installed)

    async def revoke_unexpired(
        self,
        revoke: Callable[[str], Awaitable[None]],
        *,
        now: datetime | None = None,
    ) -> None:
        """Revoke every recorded token that has not yet expired. Never raises.

        Each token is attempted independently and a failure is logged, not
        raised: this runs at teardown, after the work has been pushed, and a
        token that could not be revoked still dies on GitHub's clock within
        the hour. An exception here would cost the rest of teardown - the
        container destruction included - for a benefit measured in minutes.
        """
        moment = now if now is not None else datetime.now(UTC)
        for token in self._issued:
            if token.expires_at <= moment:
                continue
            try:
                await revoke(token.token)
            except Exception as unrevoked:
                logger.warning(
                    "Could not revoke an installation token for installation %s "
                    "(repositories=%s, expires_at=%s): %s. It stays usable until it expires.",
                    token.installation_id,
                    ",".join(token.repositories) or "<installation-wide>",
                    token.expires_at.isoformat(),
                    unrevoked,
                )
                continue
            logger.info(
                "Revoked an installation token for installation %s (expires_at was %s)",
                token.installation_id,
                token.expires_at.isoformat(),
            )
