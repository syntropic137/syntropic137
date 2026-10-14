"""SYN_EXECUTION_PROCESS_ROLE decides what production startup runs (#1310 1.6).

One image, two roles (ADR-072 D1). Driven through ``lifecycle`` itself, because
the role is only real where startup reads it: ``api`` starts the subscription
and pollers and resolves the previous process, never the host; ``executor``
starts only storage and the host, and with the Run Queue off it does nothing a
running stack could notice, which is what keeps the upgrade dark.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_api.services import execution_host_runner as runner
from syn_api.services import lifecycle, process_role
from syn_shared.settings import reset_settings
from syn_shared.settings.execution import ProcessRole

pytestmark = [pytest.mark.unit, pytest.mark.anyio]


def _registry(started: list[str]) -> tuple[lifecycle._ServiceEntry, ...]:
    def entry(name: str, *, api_only: bool) -> lifecycle._ServiceEntry:
        async def init(_state: lifecycle.LifecycleState) -> None:
            started.append(name)

        return lifecycle._ServiceEntry(reason=MagicMock(name=name), init_fn=init, api_only=api_only)

    return (entry("storage", api_only=False), entry("subscription", api_only=True))


@pytest.mark.parametrize(
    ("role", "services", "resolves_previous", "starts_host"),
    [
        ("all", ["storage", "subscription"], True, True),
        ("api", ["storage", "subscription"], True, False),
        ("executor", ["storage"], False, True),
    ],
)
async def test_the_role_decides_which_services_startup_runs(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    services: list[str],
    resolves_previous: bool,
    starts_host: bool,
) -> None:
    monkeypatch.setenv("SYN_EXECUTION_PROCESS_ROLE", role)
    reset_settings()
    started: list[str] = []
    sessions, previous, host = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(lifecycle, "_SERVICE_REGISTRY", _registry(started))
    monkeypatch.setattr(process_role, "reconcile_orphaned_sessions", sessions)
    monkeypatch.setattr(process_role, "resolve_previous_process", previous)
    monkeypatch.setattr(lifecycle, "start_execution_host", host)
    try:
        await lifecycle._init_degradable_services(lifecycle.LifecycleState())
    finally:
        reset_settings()
    assert started == services
    assert (sessions.await_count, previous.await_count) == ((1, 1) if resolves_previous else (0, 0))
    assert host.await_count == (1 if starts_host else 0)


async def test_an_executor_with_the_flag_off_reaps_nothing_and_hosts_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dark upgrade: beside a flag-off api, the executor must not run the
    global reap (it would take the api's in-process containers) nor claim."""
    monkeypatch.setenv("SYN_EXECUTION_PROCESS_ROLE", "executor")
    monkeypatch.setenv("SYN_EXECUTION_RUN_QUEUE_ENABLED", "false")
    reset_settings()
    reaped, built = AsyncMock(), MagicMock()
    monkeypatch.setattr(runner, "cleanup_orphaned_containers", reaped)
    monkeypatch.setattr(runner, "reconcile_orphaned_executions", AsyncMock())
    monkeypatch.setattr(process_role, "reconcile_orphaned_sessions", AsyncMock())
    monkeypatch.setattr(lifecycle, "_SERVICE_REGISTRY", ())
    monkeypatch.setattr(runner, "get_execution_run_queue", AsyncMock(return_value=None))
    monkeypatch.setattr(runner, "ExecutionHost", built)
    try:
        await lifecycle._init_degradable_services(lifecycle.LifecycleState())
    finally:
        await runner.stop_execution_host()
        reset_settings()
    reaped.assert_not_awaited()
    built.assert_not_called()
    assert runner._host_task is None


@pytest.mark.parametrize(("queue_on", "survives"), [(True, True), (False, False)])
async def test_an_api_restart_leaves_a_live_executor_session_running(
    monkeypatch: pytest.MonkeyPatch, queue_on: bool, survives: bool
) -> None:
    """Split topology: the executor's session is live while the api restarts,
    so api startup must not sweep it to failed. Flag off keeps main's sweep:
    every execution ran in the api, so a ``running`` row there is orphaned."""
    import json
    from dataclasses import dataclass

    from event_sourcing.stores.memory_projection import MemoryProjectionStore
    from syn_domain.contexts.agent_sessions.domain.aggregate_session.AgentSessionAggregate import (
        AgentSessionAggregate,
    )
    from syn_domain.contexts.agent_sessions.domain.commands.StartSessionCommand import (
        StartSessionCommand,
    )
    from syn_domain.contexts.agent_sessions.slices.list_sessions.projection import (
        SessionListProjection,
    )

    @dataclass
    class _Projections:
        session_list: SessionListProjection

    store = MemoryProjectionStore()
    sessions = SessionListProjection(store)
    aggregate = AgentSessionAggregate()
    aggregate.start_session(
        StartSessionCommand(
            aggregate_id="session-on-executor",
            workflow_id="workflow-split",
            execution_id="exec-on-executor",
            phase_id="phase-running",
            agent_provider="codex",
        )
    )
    started = aggregate.get_uncommitted_events()[0]
    await sessions.on_session_started(json.loads(started.event.model_dump_json()))

    monkeypatch.setenv("SYN_EXECUTION_PROCESS_ROLE", "api")
    monkeypatch.setenv("SYN_EXECUTION_RUN_QUEUE_ENABLED", "true" if queue_on else "false")
    reset_settings()
    monkeypatch.setattr("syn_api._wiring.get_projection_mgr", lambda: _Projections(sessions))
    monkeypatch.setattr(lifecycle, "_SERVICE_REGISTRY", ())
    monkeypatch.setattr(process_role, "resolve_previous_process", AsyncMock())
    try:
        await lifecycle._init_degradable_services(lifecycle.LifecycleState())
    finally:
        reset_settings()
    row = await store.get(sessions.PROJECTION_NAME, "session-on-executor")
    assert row is not None
    assert (row["status"] == "running") is survives


def test_the_production_registry_keeps_dispatchers_off_the_executor() -> None:
    executor = {e.reason for e in lifecycle._role_services(ProcessRole.EXECUTOR)}
    api_only = {
        lifecycle.DegradedReason.SUBSCRIPTION_COORDINATOR,
        lifecycle.DegradedReason.EVENT_POLLER,
        lifecycle.DegradedReason.CHECK_RUN_POLLER,
    }
    assert executor
    assert not executor & api_only
    assert set(lifecycle._role_services(ProcessRole.API)) == set(lifecycle._SERVICE_REGISTRY)


def test_the_role_defaults_to_one_process(monkeypatch: pytest.MonkeyPatch) -> None:
    from syn_shared.settings.execution import ExecutionSettings

    monkeypatch.delenv("SYN_EXECUTION_PROCESS_ROLE", raising=False)
    assert ExecutionSettings(_env_file=None).process_role is ProcessRole.ALL  # type: ignore[call-arg]
