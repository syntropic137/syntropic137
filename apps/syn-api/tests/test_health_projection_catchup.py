"""/health must admit when the read models are behind (#1172).

An operator who sees `GET /api/v1/executions/{id}` return 404 for an execution
they just dispatched has to distinguish two things that look identical from
outside: a projection rebuild replaying the event store, and a build that loses
runs. On the v0.28.0-beta.6 deploy the second was nearly assumed — a rollback of
a good release — because /health said `status: healthy`, `subscription.status:
healthy` for the whole 8m46s replay and the checkpoint table was the only place
the difference was visible.

These assert on the SERIALIZED payload from the real route, not on the objects
either side of it, because the failure that survives every other kind of test is
a value computed correctly and dropped one hop later — at the merge into the
subscription block, or at the serializer.

The lag fixture is built by `measure_read_model_lag` rather than hand-written,
so it cannot be a value that would exist anyway if the measurement stopped
working.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.subscriptions.read_model_lag import ReadModelLag, measure_read_model_lag
from syn_api.services import lifecycle

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    #: Installs a lag on the subscription service and returns the parsed /health body.
    HealthProbe = Callable[[ReadModelLag], Awaitable[dict]]

# The measured deploy: head at 8726, session_summaries replaying from 0 and
# reached 4142, everything else frozen at its pre-deploy position of 8722.
HEAD = 8726
REBUILDING = "session_summaries"
REBUILDING_POSITION = 4142
FROZEN_POSITION = 8722
PEERS = ("workflow_executions", "workflow_execution_details", "dashboard_metrics")


class _SubscriptionServiceStub:
    """Stands in for the started CoordinatorSubscriptionService.

    Only the two methods /health calls. The lag it returns is produced by the
    real measurement, so these tests fail if that measurement stops reporting a
    replay — see test_read_model_lag.py for the service's own end of the chain.
    """

    def __init__(self, lag: ReadModelLag) -> None:
        self._lag = lag

    def get_status(self) -> dict:
        return {"running": True, "projection_count": 25, "realtime_enabled": True}

    async def describe_read_model_lag(self) -> ReadModelLag:
        return self._lag


def _lag_mid_rebuild() -> ReadModelLag:
    return measure_read_model_lag(
        head_position=HEAD,
        checkpoints={REBUILDING: REBUILDING_POSITION} | dict.fromkeys(PEERS, FROZEN_POSITION),
        projection_names=[REBUILDING, *PEERS],
        replaying=True,
    )


def _lag_caught_up() -> ReadModelLag:
    return measure_read_model_lag(
        head_position=HEAD,
        checkpoints=dict.fromkeys((REBUILDING, *PEERS), HEAD),
        projection_names=[REBUILDING, *PEERS],
        replaying=False,
    )


@pytest.fixture
async def health_payload() -> AsyncIterator[HealthProbe]:
    """Yields a callable that installs a lag and returns the parsed /health JSON."""
    from syn_api.main import create_app

    original = lifecycle._state.subscription_service
    app = create_app()

    async def get(lag: ReadModelLag) -> dict:
        lifecycle._state.subscription_service = _SubscriptionServiceStub(lag)  # type: ignore[assignment]  # stub
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
        assert response.status_code == 200
        # Through the wire format, so a field the serializer drops is caught.
        return json.loads(response.text)

    try:
        yield get
    finally:
        lifecycle._state.subscription_service = original


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_rebuild_is_visible_and_names_the_projection(health_payload: HealthProbe) -> None:
    """(a) A client reading only the payload learns it is a rebuild, how far
    behind, in what unit, and which projection is holding it up."""
    body = await health_payload(_lag_mid_rebuild())

    subscription = body["subscription"]
    assert subscription["is_catching_up"] is True
    assert subscription["lag"] == HEAD - REBUILDING_POSITION
    assert subscription["lag_unit"] == "events"
    assert subscription["head_position"] == HEAD
    assert subscription["lagging_projections"][0]["projection"] == REBUILDING
    assert subscription["lagging_projections"][0]["position"] == REBUILDING_POSITION


@pytest.mark.unit
@pytest.mark.asyncio
async def test_caught_up_reports_healthy(health_payload: HealthProbe) -> None:
    """(b) No replay, no lag, nothing degraded."""
    body = await health_payload(_lag_caught_up())

    assert body["status"] == "healthy"
    assert body["mode"] == "full"
    assert "degraded_reasons" not in body
    assert body["subscription"]["is_catching_up"] is False
    assert body["subscription"]["status"] == "healthy"
    assert body["subscription"]["lag"] == 0
    assert body["subscription"]["lagging_projections"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_two_states_differ_in_the_payload_alone(health_payload: HealthProbe) -> None:
    """(c) The whole point: a client with no database access can tell them apart.

    Asserted as a difference between two real responses rather than against
    remembered literals, so a change that made both say the same thing fails
    here however that sameness was reached.
    """
    rebuilding = await health_payload(_lag_mid_rebuild())
    caught_up = await health_payload(_lag_caught_up())

    assert rebuilding != caught_up

    # `status` deliberately stays "healthy": the process is alive and accepting
    # writes during a rebuild, and it is what liveness probes read. Degradation
    # is reported on the axis this model already uses for "up but not fully
    # serving" — mode plus a named reason.
    assert caught_up["mode"] == "full"
    assert rebuilding["mode"] == "degraded"
    assert "projection_catchup" in rebuilding["degraded_reasons"]
    assert rebuilding["subscription"]["status"] == "catching_up"
    assert caught_up["subscription"]["status"] == "healthy"
