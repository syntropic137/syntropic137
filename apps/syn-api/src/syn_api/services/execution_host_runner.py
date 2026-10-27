"""Run this process's ExecutionHost when the Run Queue is on (#1310 1.5, ADR-072).

With ``SYN_EXECUTION_RUN_QUEUE_ENABLED`` off, ``resolve_previous_process`` is
main's startup reap and reconcile, ``get_execution_run_queue`` is None and no
host starts: the flag-off path is main's. With it on, admission only writes the
queue (1.3), and this host is what drains it.

``lifecycle`` calls ``resolve_previous_process`` before the subscription opens,
``start_execution_host`` last at startup and ``stop_execution_host`` first at
shutdown.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from datetime import timedelta
from typing import TYPE_CHECKING

from syn_adapters.execution_host import AggregateRunInterrupter, ExecutionHost
from syn_adapters.storage.repositories import (
    get_execution_event_stream,
    get_workflow_execution_repository,
)
from syn_adapters.workspace_backends.backend_kit import BackendKit
from syn_adapters.workspace_backends.e2b.recovery_kit import E2BRecoveryKit, E2BRunReaper
from syn_adapters.workspace_backends.host_labels import (
    LABEL_HOST_GENERATION,
    LABEL_HOST_ID,
    host_labels,
)
from syn_api._wiring import get_execution_processor, get_execution_run_queue
from syn_api._wiring_admission import get_execution_budget
from syn_api.services.dead_host_reaper import DockerDeadHostReaper
from syn_api.services.reconciliation import (
    cleanup_orphaned_containers,
    reconcile_orphaned_executions,
)
from syn_api.services.unlabelled_containers import reap_unlabelled_if_alone
from syn_domain.contexts.orchestration import HOST_CREDENTIALS, ORCHESTRATION_EVENT_EPOCH
from syn_domain.contexts.orchestration.ports import (
    Capability,
    ExecutorHost,
    ExecutorPool,
)
from syn_shared.settings import get_settings

if TYPE_CHECKING:
    from datetime import datetime

    from pydantic import SecretStr

    from syn_adapters.execution_host import RunReaper

logger = logging.getLogger(__name__)

_host_task: asyncio.Task[None] | None = None
_executor: ExecutionHost | None = None


async def resolve_previous_process(*, started_before: datetime) -> None:
    """Main's global startup reap and reconcile, except with the Run Queue on.

    With the queue on, neither runs. An admitted run is RUNNING with no
    container while it waits durably for a claim, so failing every pre-restart
    RUNNING execution would destroy exactly what the queue keeps. And another
    executor may be live, so a global reap could remove its containers. The
    previous process's claimed runs are fenced on Lease expiry and reaped by its
    own ``syn.host_id`` instead (ADR-072 D5, D6); its registration is retired by
    this process's ``register`` (D5 Restart).
    """
    if get_settings().execution.run_queue_enabled:
        logger.info("Run Queue on: startup reap is host-scoped by Lease expiry (ADR-072 D5)")
        return
    cleanup = await cleanup_orphaned_containers()
    # AFTER the reap, and only if the reap can say it finished: "this execution
    # is still running" is provably false only once every container is gone.
    await reconcile_orphaned_executions(cleanup, started_before=started_before)


async def start_execution_host() -> None:
    """Join the Executor Pool, then start the claim loop, once; a no-op with the Run Queue off.

    Raises ``PoolDefinitionConflict`` when live members of the pool declare a
    different definition, before any loop starts. The host id is the ``syn.host_id`` label this process stamps on its
    containers, so a reconciler's reap of this host finds exactly them.
    """
    global _host_task, _executor
    if _host_task is not None and not _host_task.done():
        return
    queue = await get_execution_run_queue()
    if queue is None:
        return
    labels = host_labels()
    on_e2b = get_settings().e2b.enabled
    reaper = _e2b_reaper(get_settings().e2b.api_key) if on_e2b else DockerDeadHostReaper()
    kits = _recovery_kits(reaper)
    host = ExecutorHost(
        host_id=labels[LABEL_HOST_ID],  # per process with the flag on (D5)
        container_id=socket.gethostname(),
        generation=labels[LABEL_HOST_GENERATION],
        epoch=ORCHESTRATION_EVENT_EPOCH,
        reap_scope=reaper.scope(),
        pool=_executor_pool(reaper, supplies_credentials=_supplies_credentials()),
        recovery_scopes=frozenset(kit.scope() for kit in kits),
    )
    executor = ExecutionHost(
        queue,
        host,
        # The budget sized from host capacity at startup (#1715), the same
        # limit the in-process claim path enforces.
        capacity=get_execution_budget().limit,
        drainer=await get_execution_processor(),
        reaper=reaper,
        interrupter=AggregateRunInterrupter(get_workflow_execution_repository()),
        streams=get_execution_event_stream(),
        recovery=kits,
    )
    if not on_e2b:
        # Docker only: an E2B executor's sandboxes all carry their owner (D6).
        await reap_unlabelled_if_alone(queue, host.host_id)
    # Awaited, not left to the task: a pool this process may not join refuses
    # startup rather than leaving a healthy-looking API with no claim loop (D13).
    await executor.join()
    _executor = executor
    _host_task = asyncio.create_task(executor.run_until_drained(), name="execution-host")
    _host_task.add_done_callback(_report_exit)
    logger.info("ExecutionHost %s claiming from the Run Queue", host.host_id)


def _e2b_reaper(api_key: SecretStr | None) -> RunReaper:
    """The E2B executor's reaper: a Recovery Kit on its own account (#1917).

    One executor drives one backend (research decision 1), so with E2B on this
    process reaps sandboxes, never Docker containers, and never falls back to
    Docker (decision 9). ``E2BSettings`` refuses to load enabled without a key.
    """
    _refuse_unverified_e2b_reap()
    if api_key is None:
        raise RuntimeError("SYN_E2B_ENABLED without SYN_E2B_API_KEY")
    return E2BRunReaper(E2BRecoveryKit.for_key(api_key))


class UnverifiedE2BReap(RuntimeError):
    """The E2B executor would free slots on an unconfirmed E2B listing (#1916)."""


def _refuse_unverified_e2b_reap() -> None:
    """Refuse the E2B executor outside test/offline until its reap is verifiable.

    Its reap trusts E2B's label listing, which can omit a live sandbox, so an
    empty listing could free a slot over a sandbox still running (codex review
    of #2153, accepted as a limit by ruling). Production waits for each sandbox
    to be confirmed gone by a durably recorded id. The check is the ADR-060
    one, ``uses_in_memory_stores`` (test or offline), never the e2b SDK's
    ImportError, which goes away when the SDK is installed.
    """
    # TODO(#1916): drop this guard once remote reaps confirm sandboxes by recorded id.
    if not get_settings().uses_in_memory_stores:
        raise UnverifiedE2BReap(
            "SYN_E2B_ENABLED with SYN_EXECUTION_RUN_QUEUE_ENABLED: the E2B executor's reap "
            "trusts E2B's sandbox listing, which can omit a live sandbox, so it is refused "
            "outside test/offline until reaps confirm sandboxes by recorded id "
            "(https://github.com/syntropic137/syntropic137/issues/1916)."
        )


def _recovery_kits(reaper: RunReaper) -> tuple[RunReaper, ...]:
    """The Recovery Kits this executor holds besides its own backend (C8).

    With ``SYN_E2B_RECOVERY_API_KEY`` set, a local executor reconciles a dead
    E2B executor's runs. Without it, it never fences one.
    """
    key = get_settings().e2b.recovery_api_key
    if key is None:
        return ()
    kit = E2BRunReaper(E2BRecoveryKit.for_key(key))
    return () if kit.scope() == reaper.scope() else (kit,)


def _supplies_credentials() -> bool:
    """From the backend's kit, never a setting: E2B is NoCredentials (#1914, #1917)."""
    e2b = get_settings().e2b
    if not e2b.enabled:
        return HOST_CREDENTIALS.supplies_credentials
    kit = BackendKit.e2b(e2b.template, cpu_count=e2b.cpu_count, memory_mb=e2b.memory_mb)
    return kit.credential_policy.supplies_credentials


def _executor_pool(reaper: RunReaper, *, supplies_credentials: bool = True) -> ExecutorPool:
    """The Executor Pool this process declares (ADR-072 D13).

    Provider and isolation are what this process's workspaces actually run on,
    so they come from the backend's reaper; they are never settings.
    """
    settings = get_settings().executor_pool
    return ExecutorPool(
        pool_id=settings.id,
        priority=settings.priority,
        provider=reaper.provider(),
        region=settings.region,
        isolation=reaper.isolation(),
        capabilities=frozenset(Capability(name) for name in settings.capabilities),
        overflow_delay=timedelta(seconds=settings.overflow_delay_s),
        overflow_budget_usd_per_day=settings.overflow_budget_usd_per_day,
        supplies_credentials=supplies_credentials,
    )


async def stop_execution_host() -> None:
    """Cancel the loop: held runs take the interruption path, rows await their lease.

    Then leave the pool, which the loop has done already unless it was
    cancelled before its first step. Never raises: a host that already crashed
    was reported by ``_report_exit``.
    """
    global _host_task, _executor
    task, _host_task = _host_task, None
    executor, _executor = _executor, None
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
    if executor is not None:
        await executor.leave()


def _report_exit(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "ExecutionHost stopped: admitted runs will not be claimed by this process",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
