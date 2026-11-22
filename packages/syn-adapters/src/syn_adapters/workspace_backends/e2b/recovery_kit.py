"""The E2B Recovery Kit and the E2B executor's reaper (#1917, research decision 8, C8).

A **Recovery Kit** is the narrow capability to clean up after a dead executor
on one backend and account: list the sandboxes an owner left for one run,
attach to each with the ownership check, and kill it. It is separate from
provisioning: it creates nothing, runs nothing and reads nothing, so it can sit
on a local Docker executor that never runs an E2B workspace.

The transport stays in agentic-workspace: ``list_owned``, ``attach`` and
``destroy`` (kill, then wait until E2B no longer knows the id) are the
``E2BWorkspaceProvider``'s own, so a change in the E2B SDK changes nothing here.

``E2BRunReaper`` is a ``RunReaper`` over a kit. The E2B executor reaps its own
runs with it before close (D3), and any executor holding a kit for that account
reconciles the E2B executor's runs after it dies (D5). Every sandbox carries
``syn.host_id`` and ``syn.execution_id`` metadata from creation, so a create
whose response was lost is still listed.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Protocol

from agentic_isolation import E2BWorkspaceProvider, SupportsOwnership, WorkspaceNotFoundError

from syn_adapters.workspace_backends.host_labels import LABEL_HOST_ID
from syn_domain.contexts.orchestration.ports import IsolationLevel

if TYPE_CHECKING:
    from collections.abc import Mapping

    from agentic_isolation import TeardownReport, Workspace
    from agentic_isolation.providers.e2b_client import E2BSandboxClient
    from pydantic import SecretStr

    from syn_domain.contexts.orchestration.ports import ProviderId, ReapScope

logger = logging.getLogger(__name__)

LABEL_EXECUTION_ID = "syn.execution_id"
# The kit never creates, so the provider's template is never read.
_NO_TEMPLATE = "recovery-kit-creates-nothing"


def e2b_reap_scope(api_key: SecretStr) -> ReapScope:
    """The reap scope an E2B API key reaches: one E2B account, by a digest of its key.

    Derived, never configured (D13). Only a digest is recorded, never the key.
    A kit holding a different key for the same account gets a different scope,
    so it never fences there: that strands a run safely (the D5 alert) rather
    than fence one it may be unable to list.
    """
    digest = hashlib.sha256(api_key.get_secret_value().encode()).hexdigest()
    return f"e2b-key-{digest[:16]}"


class RecoverableBackend(SupportsOwnership, Protocol):
    """What a kit uses of a provider: list owned, attach with ownership, destroy."""

    async def destroy(self, workspace: Workspace) -> TeardownReport: ...


class E2BRecoveryKit:
    """List, attach (with ownership) and kill on one E2B account; nothing else."""

    def __init__(self, backend: RecoverableBackend, scope: ReapScope) -> None:
        self._backend = backend
        self._scope = scope

    @classmethod
    def for_key(
        cls, api_key: SecretStr, *, client: E2BSandboxClient | None = None
    ) -> E2BRecoveryKit:
        """A kit on the account ``api_key`` reaches; ``client`` is a test double's seam."""
        if client is None:
            from agentic_isolation.providers.e2b_client import SdkE2BClient

            client = SdkE2BClient(api_key=api_key.get_secret_value())
        return cls(E2BWorkspaceProvider(_NO_TEMPLATE, client=client), e2b_reap_scope(api_key))

    @property
    def scope(self) -> ReapScope:
        return self._scope

    async def owned(self, labels: Mapping[str, str]) -> list[str]:
        """Ids of the sandboxes carrying all of ``labels``. Raises when E2B cannot list."""
        return [found.workspace_id for found in await self._backend.list_owned(labels)]

    async def kill(self, sandbox_id: str, labels: Mapping[str, str]) -> None:
        """Kill one sandbox, only if it still carries ``labels``; a vanished one is done.

        Raises ``WorkspaceOwnershipError`` rather than kill a sandbox another
        owner holds, and the provider's error when the removal is unconfirmed.
        """
        try:
            workspace = await self._backend.attach(sandbox_id, expect_labels=labels)
        except WorkspaceNotFoundError:
            return
        await self._backend.destroy(workspace)


class E2BRunReaper:
    """A ``RunReaper`` for E2B sandboxes, through a Recovery Kit (D3, D5, C8)."""

    def __init__(self, kit: E2BRecoveryKit) -> None:
        self._kit = kit

    def scope(self) -> ReapScope:
        return self._kit.scope

    def provider(self) -> ProviderId:
        return "e2b"

    def isolation(self) -> IsolationLevel:
        return IsolationLevel.MICROVM

    async def reap(self, executor_id: str, execution_id: str) -> bool:
        """Kill every sandbox ``executor_id`` created for ``execution_id``.

        True only when a fresh listing shows none left. A failed list or kill
        raises, which the host and the reconciler both count as not shown gone:
        the run keeps ``fencing`` and its charge (D3, D5).
        """
        labels = {LABEL_HOST_ID: executor_id, LABEL_EXECUTION_ID: execution_id}
        for sandbox_id in await self._kit.owned(labels):
            await self._kit.kill(sandbox_id, labels)
        left = await self._kit.owned(labels)
        if left:
            logger.warning(
                "E2B still lists %d sandbox(es) for %s on %s: %s",
                len(left),
                execution_id,
                executor_id,
                ", ".join(left),
            )
        return not left
