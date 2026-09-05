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

There are two ways to be behind and they need opposite responses, so /health has
to tell them apart: a rebuild ends by itself and the answer is to wait, a stalled
projection does not and the answer is to intervene. Both must be reachable from
the payload alone, and each must be visible WITHOUT the other, which is what the
independence assertions below pin. They are not exclusive: a replay that wedges
sets both, and that payload is covered too - it is the one where the single
`status` slot has to rank them while `degraded_reasons` must not.
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


# Checkpoint ages either side of the stall threshold. MOVING is the mid-dispatch
# sample a busy deployment produces constantly; STUCK is past anything the
# coordinator's own reconnect backoff can account for.
NOW = datetime(2025, 11, 3, 6, 9, 35, tzinfo=UTC)
MOVING = NOW - timedelta(seconds=1)
STUCK = NOW - timedelta(seconds=STALLED_AFTER_SECONDS + 1)


def _lag_mid_rebuild() -> ReadModelLag:
    """A replay in flight: everyone behind, every checkpoint still advancing."""
    return measure_read_model_lag(
        head_position=HEAD,
        checkpoints={
            REBUILDING: CheckpointState(position=REBUILDING_POSITION, updated_at=MOVING),
            **{
                name: CheckpointState(position=FROZEN_POSITION, updated_at=MOVING) for name in PEERS
            },
        },
        projection_names=[REBUILDING, *PEERS],
        replaying=True,
        now=NOW,
    )


def _lag_wedged() -> ReadModelLag:
    """One projection stuck with no replay to explain it: peers at the head, the
    coordinator live, and a checkpoint that has not moved in over two minutes."""
    return measure_read_model_lag(
        head_position=HEAD,
        checkpoints={
            REBUILDING: CheckpointState(position=REBUILDING_POSITION, updated_at=STUCK),
            **{name: CheckpointState(position=HEAD, updated_at=MOVING) for name in PEERS},
        },
        projection_names=[REBUILDING, *PEERS],
        replaying=False,
        now=NOW,
    )


def _lag_rebuild_wedged_before_its_first_checkpoint() -> ReadModelLag:
    """A rebuild that failed on the FIRST event it was replayed.

    Version reconciliation deletes the checkpoint row before the replay, and a
    projection that raises on its first event never writes a replacement - so
    there is no row whose `updated_at` could be old. The service supplies its own
    start time as the age of that absence, which is what `position: 0` with a
    stale `updated_at` stands for here.

    Both signals are true: a replay IS running, and this projection is not moving
    through it. Left to `is_catching_up` alone the payload says "wait" about a
    rebuild that will never finish.
    """
    return measure_read_model_lag(
        head_position=HEAD,
        checkpoints={
            REBUILDING: CheckpointState(position=0, updated_at=STUCK),
            **{
                name: CheckpointState(position=FROZEN_POSITION, updated_at=MOVING) for name in PEERS
            },
        },
        projection_names=[REBUILDING, *PEERS],
        replaying=True,
        now=NOW,
    )


def _lag_steady_state() -> ReadModelLag:
    """The sample a busy deployment produces all day: one projection a single
    event behind, checkpoint just written, no replay. Must read as healthy."""
    return measure_read_model_lag(
        head_position=HEAD,
        checkpoints={
            REBUILDING: CheckpointState(position=HEAD - 1, updated_at=MOVING),
            **{name: CheckpointState(position=HEAD, updated_at=MOVING) for name in PEERS},
        },
        projection_names=[REBUILDING, *PEERS],
        replaying=False,
        now=NOW,
    )


def _lag_caught_up() -> ReadModelLag:
    return measure_read_model_lag(
        head_position=HEAD,
        checkpoints={
            name: CheckpointState(position=HEAD, updated_at=MOVING) for name in (REBUILDING, *PEERS)
        },
        projection_names=[REBUILDING, *PEERS],
        replaying=False,
        now=NOW,
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
    behind, in what unit, and which projection is holding it up — and that the
    rebuild is still moving, so the answer is to wait rather than to intervene."""
    body = await health_payload(_lag_mid_rebuild())

    subscription = body["subscription"]
    assert subscription["is_catching_up"] is True
    assert subscription["lag"] == HEAD - REBUILDING_POSITION
    assert subscription["lag_unit"] == "events"
    assert subscription["head_position"] == HEAD
    assert subscription["lagging_projections"][0]["projection"] == REBUILDING
    assert subscription["lagging_projections"][0]["position"] == REBUILDING_POSITION

    # Degraded, and named as the waiting kind.
    assert body["mode"] == "degraded"
    assert body["degraded_reasons"] == ["projection_catchup"]
    assert subscription["status"] == "catching_up"

    # The other signal stays down. Serialized, because a payload that raised
    # both here would be telling an operator to intervene in a healthy rebuild.
    assert subscription["is_stalled"] is False
    assert subscription["lagging_projections"][0]["stalled"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_caught_up_reports_healthy(health_payload: HealthProbe) -> None:
    """(d) No replay, no lag, neither signal, nothing degraded."""
    body = await health_payload(_lag_caught_up())

    assert body["status"] == "healthy"
    assert body["mode"] == "full"
    assert "degraded_reasons" not in body
    assert body["subscription"]["is_catching_up"] is False
    assert body["subscription"]["is_stalled"] is False
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_wedged_projection_is_visible_and_named(health_payload: HealthProbe) -> None:
    """(b) A projection stuck with no replay to explain it, off the wire.

    This is the state that used to serialize as `is_catching_up: false`, `mode:
    full`, `status: healthy` — a healthy verdict over a read model that is stuck
    until a human does something, which is worse than the blackout this issue
    was filed about because it never resolves on its own.
    """
    body = await health_payload(_lag_wedged())

    subscription = body["subscription"]
    assert subscription["is_stalled"] is True

    # Degraded, and named as the kind that needs a human.
    assert body["mode"] == "degraded"
    assert "projection_stalled" in body["degraded_reasons"]
    assert subscription["status"] == "stalled"

    # Named, with the evidence: which projection, how far behind, how long stuck.
    stuck = subscription["lagging_projections"][0]
    assert stuck["projection"] == REBUILDING
    assert stuck["stalled"] is True
    assert stuck["checkpoint_age_seconds"] == STALLED_AFTER_SECONDS + 1

    # Independently observable: no rebuild is claimed, and no rebuild reason is
    # raised. An operator told to wait here would wait forever.
    assert subscription["is_catching_up"] is False
    assert "projection_catchup" not in body["degraded_reasons"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_wedged_rebuild_reports_both_signals_on_the_wire(
    health_payload: HealthProbe,
) -> None:
    """(e) Both signals true at once, through the serializer.

    The single `status` slot has to rank them and the reasons list must not, so
    this is the one payload where the two renderings of the verdict can disagree
    - a status that leads with the stall while the catch-up reason silently
    disappears, or the reverse. Asserting the reasons as a whole list rather than
    with `in` is what makes a dropped one fail here.
    """
    body = await health_payload(_lag_rebuild_wedged_before_its_first_checkpoint())

    subscription = body["subscription"]
    assert subscription["is_catching_up"] is True
    assert subscription["is_stalled"] is True

    # Degraded once, with EVERY reason that fired - an operator filtering on
    # `projection_stalled` and one filtering on `projection_catchup` both see it.
    # Asserted as a whole list, in severity order, so a reason dropped when the
    # other outranks it fails here rather than passing an `in` check.
    assert body["mode"] == "degraded"
    assert body["degraded_reasons"] == ["projection_stalled", "projection_catchup"]
    # The slot that holds one value leads with the one needing a human, and it
    # agrees with the head of the list because both are read off the same rows.
    assert subscription["status"] == "stalled"

    # Named, at position 0: the rebuild never got its first checkpoint written.
    stuck = subscription["lagging_projections"][0]
    assert stuck["projection"] == REBUILDING
    assert stuck["position"] == 0
    assert stuck["stalled"] is True
    assert stuck["checkpoint_age_seconds"] == STALLED_AFTER_SECONDS + 1
    # The peers are behind too - a replay holds everyone back - and are not stuck.
    assert [
        entry["projection"] for entry in subscription["lagging_projections"] if entry["stalled"]
    ] == [REBUILDING]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ordinary_steady_state_lag_stays_healthy(health_payload: HealthProbe) -> None:
    """(c) The anti-flapping guarantee, pinned on the payload.

    Checkpoints advance per event, so a sample taken mid-dispatch on any busy
    deployment finds someone one event behind. If that degraded /health the
    endpoint would be degraded most of the time under load and operators would
    stop reading it — which is the failure this whole block exists to avoid.
    """
    body = await health_payload(_lag_steady_state())

    assert body["status"] == "healthy"
    assert body["mode"] == "full"
    assert "degraded_reasons" not in body
    assert body["subscription"]["status"] == "healthy"
    # Neither signal, even though a projection IS measurably behind.
    assert body["subscription"]["is_catching_up"] is False
    assert body["subscription"]["is_stalled"] is False
    assert body["subscription"]["lag"] == 1
    assert body["subscription"]["lagging_projections"][0]["stalled"] is False
