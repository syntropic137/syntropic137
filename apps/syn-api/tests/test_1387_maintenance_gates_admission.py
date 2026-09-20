"""Every admission after the set call returns is refused (#1387).

The deploy drain used to only observe. It polled status counts until they were
terminal and then swapped containers, and nothing stopped work arriving in the
gap: ``POST /workflows/{id}/execute`` returns before its BackgroundTask has
persisted anything, so the projection can truthfully report a quiet system
while accepted work is about to start. One execution lost in that window was
worth 131M tokens and $96.91.

So the assertions here are about what the ENDPOINT does, not about what the
flag says. The one that matters most is that no background task is queued: a
409 with the task still scheduled would be the same lost execution with a
better status code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import pytest
from fastapi import BackgroundTasks, HTTPException

os.environ.setdefault("APP_ENVIRONMENT", "test")

from syn_api.routes.executions.commands import execute_workflow_endpoint
from syn_api.routes.maintenance import get_maintenance_mode, set_maintenance_mode
from syn_api.types import SetMaintenanceModeRequest

pytestmark = pytest.mark.unit


@dataclass
class _Request:
    """Enough of ExecuteWorkflowRequest for the endpoint's signature."""

    inputs: dict[str, str] = field(default_factory=dict)
    repos: list[str] = field(default_factory=list)
    task: str | None = None
    provider: str = "claude"


class _FakeRedis:
    """A store that outlives the adapter reading it - i.e. a restart."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value


@pytest.fixture(autouse=True)
def _fresh_maintenance_port() -> object:
    """Each test gets its own gate; none of them inherit another's state."""
    import syn_api._wiring as wiring

    wiring._maintenance_singleton = None
    yield
    wiring._maintenance_singleton = None


async def _admit(workflow_id: str = "wf-does-not-exist") -> BackgroundTasks:
    """Call the endpoint and return the tasks it queued.

    ``wf-does-not-exist`` is deliberate: with the gate OPEN this reaches
    validation and 404s, so a 409 can only have come from the gate and a 404
    proves the gate let the request through. Nothing here needs a real
    workflow, because nothing here is testing workflows.
    """
    tasks = BackgroundTasks()
    await execute_workflow_endpoint(workflow_id, _Request(), tasks)  # type: ignore[arg-type]
    return tasks


class TestTheHttpPathRefusesWhileAdmissionIsPaused:
    async def test_execute_returns_409_and_queues_nothing(self) -> None:
        await set_maintenance_mode(
            SetMaintenanceModeRequest(active=True, reason="pit stop 0.29.1", actor="deploy")
        )

        tasks = BackgroundTasks()
        with pytest.raises(HTTPException) as exc:
            await execute_workflow_endpoint("wf-does-not-exist", _Request(), tasks)  # type: ignore[arg-type]

        assert exc.value.status_code == 409
        assert "pit stop 0.29.1" in str(exc.value.detail)
        assert tasks.tasks == [], (
            "the endpoint refused but still queued the execution - "
            "the BackgroundTask is what actually admits the work"
        )

    async def test_the_refusal_precedes_validation(self) -> None:
        """A paused gate answers 409 for a workflow that does not exist.

        If the check ran after ``_validate_execution_request`` the caller would
        get 404 and conclude the deploy gate had nothing to do with it.
        """
        await set_maintenance_mode(
            SetMaintenanceModeRequest(active=True, reason="pit stop", actor="deploy")
        )

        with pytest.raises(HTTPException) as exc:
            await _admit()

        assert exc.value.status_code == 409

    async def test_the_same_call_is_not_a_409_while_the_gate_is_open(self) -> None:
        """The negative control. Without it a 409 for every request would pass."""
        with pytest.raises(HTTPException) as exc:
            await _admit()

        assert exc.value.status_code == 404

    async def test_clearing_the_flag_reopens_admission(self) -> None:
        """The far side of the swap - the deploy's last step."""
        await set_maintenance_mode(
            SetMaintenanceModeRequest(active=True, reason="pit stop", actor="deploy")
        )
        await set_maintenance_mode(
            SetMaintenanceModeRequest(active=False, reason="", actor="deploy")
        )

        with pytest.raises(HTTPException) as exc:
            await _admit()

        assert exc.value.status_code == 404


class TestARestartedApiComesBackStillRefusing:
    """The swap destroys the container that was told to stop admitting.

    Simulated at the only level where it is observable in-process: the port is
    replaced with a brand-new adapter over the same store, which is exactly
    what the replacement container builds at startup.
    """

    async def test_a_fresh_adapter_over_the_same_store_still_refuses(self) -> None:
        import syn_api._wiring as wiring
        from syn_adapters.maintenance import RedisMaintenanceAdapter

        backend = _FakeRedis()
        wiring._maintenance_singleton = RedisMaintenanceAdapter(backend)  # type: ignore[arg-type]
        await set_maintenance_mode(
            SetMaintenanceModeRequest(active=True, reason="pit stop", actor="deploy")
        )

        # The swap: this process's adapter is gone, a new one reads the store.
        wiring._maintenance_singleton = RedisMaintenanceAdapter(backend)  # type: ignore[arg-type]

        with pytest.raises(HTTPException) as exc:
            await _admit()
        assert exc.value.status_code == 409
        assert (await get_maintenance_mode()).active is True

    async def test_the_set_call_does_not_return_before_the_state_is_durable(self) -> None:
        """No window on the setting side either.

        A reader that never saw the adapter which performed the write - and so
        cannot be reading anything it cached - already sees the new state by
        the time the PUT's response exists.
        """
        import syn_api._wiring as wiring
        from syn_adapters.maintenance import RedisMaintenanceAdapter

        backend = _FakeRedis()
        wiring._maintenance_singleton = RedisMaintenanceAdapter(backend)  # type: ignore[arg-type]

        await set_maintenance_mode(
            SetMaintenanceModeRequest(active=True, reason="pit stop", actor="deploy")
        )

        independent = RedisMaintenanceAdapter(backend)  # type: ignore[arg-type]
        assert (await independent.current()).active is True


class TestTheReportedState:
    async def test_get_reports_what_was_set(self) -> None:
        await set_maintenance_mode(
            SetMaintenanceModeRequest(active=True, reason="pit stop 0.29.1", actor="deploy")
        )

        reported = await get_maintenance_mode()

        assert reported.active is True
        assert reported.reason == "pit stop 0.29.1"
        assert reported.actor == "deploy"
        assert reported.since is not None

    async def test_an_untouched_system_reports_open(self) -> None:
        reported = await get_maintenance_mode()

        assert reported.active is False
        assert reported.since is None
