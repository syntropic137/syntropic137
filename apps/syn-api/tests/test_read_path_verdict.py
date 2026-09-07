"""The read-path verdict, and the signal /health never had a test for.

`_judge_read_path` moved out of `lifecycle` into its own module (#1172); the
imports below are what pin it to that home, so this file fails to collect if it
drifts back or gets duplicated.

What is asserted, though, is not the move. The severity table has three rows and
until now only two of them were ever exercised: every case in
test_health_projection_catchup.py runs with a coordinator that is `running`, so
the row that fires when it is NOT — the one that outranks both lag signals — was
unreached from any test. That row is the difference between "wait, a rebuild is
in flight" and "nothing is consuming events at all", and an operator reading the
second as the first waits forever.

Asserted on the serialized payload from the real route, like its sibling file,
because the ranking has to survive the hop into the subscription block and the
serializer: `status` holds one value and must lead with the coordinator, while
`degraded_reasons` must still carry the rebuild that is also true.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.subscriptions.read_model_lag import (
    STALLED_AFTER_SECONDS,
    CheckpointState,
    ReadModelLag,
    measure_read_model_lag,
)
from syn_api.services import lifecycle
from syn_api.services.degraded_reasons import DegradedReason
from syn_api.services.read_path_health import _judge_read_path

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    #: Installs a subscription state and returns the parsed /health body.
    HealthProbe = Callable[[bool, ReadModelLag | None], Awaitable[dict]]

HEAD = 8726
REBUILDING = "session_summaries"
REBUILDING_POSITION = 4142
PEER = "workflow_executions"

NOW = datetime(2025, 11, 3, 6, 9, 35, tzinfo=UTC)
MOVING = NOW - timedelta(seconds=1)
STUCK = NOW - timedelta(seconds=STALLED_AFTER_SECONDS + 1)


class _SubscriptionServiceStub:
    """The started coordinator, with `running` under the test's control.

    Its sibling file's stub is always running, which is the whole gap this file
    covers: a coordinator that stopped still answers `describe_read_model_lag`
    from the checkpoint table, so the lag looks like an ordinary rebuild.
    """

    def __init__(self, running: bool, lag: ReadModelLag | None) -> None:
        self._running = running
        self._lag = lag

    def get_status(self) -> dict:
        return {"running": self._running, "projection_count": 25, "realtime_enabled": True}

    async def describe_read_model_lag(self) -> ReadModelLag | None:
        return self._lag


def _lag_mid_rebuild() -> ReadModelLag:
    """A replay in flight, measured rather than hand-written: behind, still moving."""
    return measure_read_model_lag(
        head_position=HEAD,
        checkpoints={
            REBUILDING: CheckpointState(position=REBUILDING_POSITION, updated_at=MOVING),
            PEER: CheckpointState(position=HEAD, updated_at=MOVING),
        },
        projection_names=[REBUILDING, PEER],
        replaying=True,
        now=NOW,
    )


def _lag_wedged() -> ReadModelLag:
    """One projection stuck with no replay to explain it."""
    return measure_read_model_lag(
        head_position=HEAD,
        checkpoints={
            REBUILDING: CheckpointState(position=REBUILDING_POSITION, updated_at=STUCK),
            PEER: CheckpointState(position=HEAD, updated_at=MOVING),
        },
        projection_names=[REBUILDING, PEER],
        replaying=False,
        now=NOW,
    )


@pytest.fixture
async def health_payload() -> AsyncIterator[HealthProbe]:
    """Yields a callable that installs a subscription state and returns /health."""
    from syn_api.main import create_app

    original = lifecycle._state.subscription_service
    app = create_app()

    async def get(running: bool, lag: ReadModelLag | None) -> dict:
        lifecycle._state.subscription_service = _SubscriptionServiceStub(running, lag)  # type: ignore[assignment]  # stub
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
        assert response.status_code == 200
        return json.loads(response.text)

    try:
        yield get
    finally:
        lifecycle._state.subscription_service = original


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_dead_coordinator_outranks_the_rebuild_it_looks_like(
    health_payload: HealthProbe,
) -> None:
    """A stopped coordinator during a replay: both true, and the ranking matters.

    The lag on its own is indistinguishable from a healthy rebuild - projections
    behind the head, checkpoints written a second ago - so reported as
    `catching_up` this payload tells an operator to wait for a replay that has
    nobody left to advance it. `status` must lead with the coordinator.
    """
    body = await health_payload(False, _lag_mid_rebuild())

    subscription = body["subscription"]
    assert subscription["running"] is False
    assert subscription["is_catching_up"] is True

    assert subscription["status"] == "degraded"
    assert body["mode"] == "degraded"
    # The whole list, in severity order: the rebuild is still true and an
    # operator filtering on `projection_catchup` must still see this deployment.
    assert body["degraded_reasons"] == ["subscription_coordinator", "projection_catchup"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_dead_coordinator_is_degraded_before_any_lag_can_be_measured(
    health_payload: HealthProbe,
) -> None:
    """No lag measurement at all - the subscription is not up yet.

    "Not measured" is not "not behind": the absence of a measurement fires no lag
    signal of its own, and `running` is the only thing left to report it. A
    payload that read the missing measurement as health would be `healthy` for a
    read path serving nothing.
    """
    body = await health_payload(False, None)

    subscription = body["subscription"]
    assert subscription["status"] == "degraded"
    assert body["mode"] == "degraded"
    assert body["degraded_reasons"] == ["subscription_coordinator"]
    # No lag fields invented from an absent measurement.
    assert "is_catching_up" not in subscription
    assert "is_stalled" not in subscription
    assert "lagging_projections" not in subscription


@pytest.mark.unit
def test_every_signal_that_fired_is_reported_and_the_worst_one_leads() -> None:
    """All three rows at once, on the verdict itself.

    Unreachable through /health with the current measurement - a stalled replay
    with a dead coordinator is three simultaneous failures - but the table has to
    rank it, and the property that makes that safe is structural: the status is
    the head of the same sequence the reasons are read from, so it can never name
    a deployment state the reasons list does not also contain.
    """
    verdict = _judge_read_path(running=False, lag=_lag_wedged())

    assert verdict.degraded_reasons == (
        DegradedReason.SUBSCRIPTION_COORDINATOR,
        DegradedReason.PROJECTION_STALLED,
    )
    assert verdict.status == "degraded"


@pytest.mark.unit
def test_a_running_coordinator_with_nothing_behind_raises_no_signal() -> None:
    """The floor: no row fires, so there is nothing for /health to report."""
    verdict = _judge_read_path(
        running=True,
        lag=measure_read_model_lag(
            head_position=HEAD,
            checkpoints={
                name: CheckpointState(position=HEAD, updated_at=MOVING)
                for name in (REBUILDING, PEER)
            },
            projection_names=[REBUILDING, PEER],
            replaying=False,
            now=NOW,
        ),
    )

    assert verdict.status == "healthy"
    assert verdict.degraded_reasons == ()
