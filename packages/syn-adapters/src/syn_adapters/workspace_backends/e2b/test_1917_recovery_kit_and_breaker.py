"""The E2B Recovery Kit, its reaper, and creates feeding the Outage Breaker (#1917).

The account is ``SandboxDouble`` driven through agentic-workspace's real
``E2BWorkspaceProvider``; nothing here reaches E2B.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from agentic_isolation import E2BWorkspaceProvider
from agentic_isolation.providers import e2b as e2b_provider
from agentic_isolation.providers.e2b_client import SandboxListing
from pydantic import SecretStr

from syn_adapters.execution_host.outage_breaker import OutageBreaker
from syn_adapters.execution_runs.memory import InMemoryExecutionRunQueue
from syn_adapters.workspace_backends.e2b.breaker_client import BreakerE2BClient
from syn_adapters.workspace_backends.e2b.recovery_kit import (
    LABEL_EXECUTION_ID,
    E2BRecoveryKit,
    E2BRunReaper,
    e2b_reap_scope,
)
from syn_adapters.workspace_backends.e2b.test_e2b_backend import SandboxDouble
from syn_adapters.workspace_backends.host_labels import LABEL_HOST_ID
from syn_domain.contexts.orchestration.ports import (
    ExecutorHost,
    ExecutorPool,
    IsolationLevel,
    RunWorkload,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.unit

_KEY = SecretStr("e2b_invented_for_test_not_real")


def _reaper(account: SandboxDouble) -> E2BRunReaper:
    provider = E2BWorkspaceProvider("unused", client=account)
    return E2BRunReaper(E2BRecoveryKit(provider, e2b_reap_scope(_KEY)))


async def _sandbox(account: SandboxDouble, host_id: str, execution_id: str) -> str:
    return await account.create(
        template="t",
        metadata={LABEL_HOST_ID: host_id, LABEL_EXECUTION_ID: execution_id},
        lifetime_seconds=60,
    )


def test_the_scope_names_the_account_by_a_digest_never_the_key() -> None:
    scope = e2b_reap_scope(_KEY)
    assert scope == e2b_reap_scope(SecretStr(_KEY.get_secret_value()))
    assert scope.startswith("e2b-key-")
    assert _KEY.get_secret_value() not in scope
    assert scope != e2b_reap_scope(SecretStr("another-key"))


def test_the_reaper_reports_the_e2b_backend() -> None:
    reaper = _reaper(SandboxDouble())
    assert (reaper.provider(), reaper.isolation()) == ("e2b", IsolationLevel.MICROVM)
    assert reaper.scope() == e2b_reap_scope(_KEY)


async def test_reap_kills_only_that_owners_sandboxes_for_that_run() -> None:
    account = SandboxDouble()
    mine = await _sandbox(account, "e2b-1", "run-1")  # its create response may have been lost
    kept = {
        await _sandbox(account, "e2b-1", "run-2"),
        await _sandbox(account, "e2b-2", "run-1"),
    }

    assert await _reaper(account).reap("e2b-1", "run-1") is True

    assert mine not in account.sandboxes
    assert set(account.sandboxes) == kept


async def test_reap_with_nothing_left_is_true() -> None:
    assert await _reaper(SandboxDouble()).reap("e2b-1", "run-1") is True


async def test_an_unconfirmed_kill_is_not_shown_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(e2b_provider, "_REMOVAL_SECONDS", 0.05)
    account = SandboxDouble(kill_is_noop=True)
    await _sandbox(account, "e2b-1", "run-1")

    with pytest.raises(e2b_provider.SandboxRemovalError):
        await _reaper(account).reap("e2b-1", "run-1")


class _LaggingList(SandboxDouble):
    """E2B's list still shows a sandbox its id lookup no longer knows."""

    def __init__(self) -> None:
        super().__init__()
        self.listed_after_kill: dict[str, dict[str, str]] = {}

    async def kill(self, sandbox_id: str) -> bool:
        self.listed_after_kill[sandbox_id] = dict(self.sandboxes[sandbox_id][0])
        return await super().kill(sandbox_id)

    async def list(self, metadata: Mapping[str, str]) -> list[SandboxListing]:
        lagging = [SandboxListing(sid, labels) for sid, labels in self.listed_after_kill.items()]
        return [*await super().list(metadata), *lagging]


async def test_a_listing_that_still_shows_a_sandbox_is_not_shown_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(e2b_provider, "_LISTING_SECONDS", 0.05)
    account = _LaggingList()
    await _sandbox(account, "e2b-1", "run-1")

    assert await _reaper(account).reap("e2b-1", "run-1") is False


# --- creates feed the Outage Breaker ---------------------------------------------


class _RefusingAccount(SandboxDouble):
    def __init__(self) -> None:
        super().__init__()
        self.refuse = True

    async def create(
        self, *, template: str, metadata: Mapping[str, str], lifetime_seconds: int
    ) -> str:
        if self.refuse:
            raise ConnectionError("E2B is down")
        return await super().create(
            template=template, metadata=metadata, lifetime_seconds=lifetime_seconds
        )


async def test_consecutive_failed_creates_disable_claims_and_a_success_clears() -> None:
    queue = InMemoryExecutionRunQueue()
    await queue.register(
        ExecutorHost(
            host_id="e2b-1",
            container_id="c",
            generation="g",
            epoch=1,
            reap_scope=e2b_reap_scope(_KEY),
            pool=ExecutorPool(
                pool_id="e2b", priority=0, provider="e2b", supplies_credentials=False
            ),
        ),
        2,
    )
    await queue.heartbeat("e2b-1")
    assert await queue.reserve("run-1", 1, is_resume=False, workload=RunWorkload.SCRIPTED)
    await queue.mark_admitted("run-1")

    async def _queue() -> InMemoryExecutionRunQueue:
        return queue

    account = _RefusingAccount()
    breaker = OutageBreaker(_queue, "e2b-1", threshold=2, cooldown=timedelta(minutes=5))
    client = BreakerE2BClient(account, breaker)
    for _ in range(2):
        with pytest.raises(ConnectionError, match="E2B is down"):
            await client.create(template="t", metadata={}, lifetime_seconds=60)

    assert await queue.claim("e2b-1") is None

    account.refuse = False
    assert await client.create(template="t", metadata={}, lifetime_seconds=60) == "sbx-1"
    assert await queue.claim("e2b-1") is not None


async def test_a_breaker_that_cannot_reach_its_row_never_masks_the_create() -> None:
    async def _down() -> InMemoryExecutionRunQueue:
        raise OSError("Postgres unreachable")

    client = BreakerE2BClient(
        _RefusingAccount(),
        OutageBreaker(_down, "e2b-1", threshold=1, cooldown=timedelta(minutes=5)),
    )
    with pytest.raises(ConnectionError, match="E2B is down"):
        await client.create(template="t", metadata={}, lifetime_seconds=60)
