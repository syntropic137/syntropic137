"""The dead-host reap selects by owner, never by name alone (#1310 1.5, ADR-072 D6).

Asserts the ``docker ps`` arguments the reap actually runs: a filter missing
``syn.host_id`` would remove a live host's workspaces (V7). Docker itself is
not run here; V7/V7b are E2E.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syn_api.services.dead_host_reaper import DockerDeadHostReaper
from syn_domain.contexts.orchestration.ports import FencedRun

pytestmark = [pytest.mark.unit, pytest.mark.anyio]

_RUN = FencedRun(execution_id="exec-dead", executor_id="host-dead", reconciler="host-live", token=3)


@pytest.fixture(autouse=True)
def _no_guard() -> object:
    """The #1560 guard's own narrowing is pinned in test_host_scoped_reap_guards_unpushed_work_first."""
    with patch(
        "syn_api.services.dead_host_reaper._guard_orphaned_workspaces",
        new=AsyncMock(return_value=[]),
    ) as guard:
        yield guard


def _ps(stdout: bytes) -> MagicMock:
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    return proc


async def test_both_selectors_are_narrowed_to_the_dead_host_and_the_run() -> None:
    spawn = AsyncMock(side_effect=[_ps(b""), _ps(b"")])
    with patch("syn_api.services.reconciliation.asyncio.create_subprocess_exec", new=spawn):
        assert await DockerDeadHostReaper().reap(_RUN.executor_id, _RUN.execution_id) is True

    calls = [call.args for call in spawn.await_args_list]
    assert len(calls) == 2
    for args, selector in zip(
        calls, ("label=syn.component=sidecar", "name=agentic-ws-"), strict=True
    ):
        filters = [args[i + 1] for i, a in enumerate(args) if a == "--filter"]
        assert filters == [
            selector,
            "label=syn.host_id=host-dead",
            "label=syn.execution_id=exec-dead",
        ]


async def test_an_unfinished_reap_is_not_reported_complete() -> None:
    timed_out = MagicMock()
    timed_out.communicate = AsyncMock(side_effect=TimeoutError)
    timed_out.wait = AsyncMock()
    spawn = AsyncMock(side_effect=[timed_out, _ps(b"")])
    with patch("syn_api.services.reconciliation.asyncio.create_subprocess_exec", new=spawn):
        assert await DockerDeadHostReaper().reap(_RUN.executor_id, _RUN.execution_id) is False
