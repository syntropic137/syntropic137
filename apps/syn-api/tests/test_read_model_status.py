"""Pages can say their read model is rebuilding, without the client doing the math.

After a deploy bumps a projection's version the execution list showed 1,109 of
~1,300 runs, newest missing, for minutes, and looked broken. The verdict and
every number a page shows come from `services.read_model_status`; these tests
pin that verdict and then read it back off the serialized responses that carry
it, because a value computed correctly and dropped one hop later passes every
test of the object that computed it.

Every lag fixture is produced by the real `measure_read_model_lag`.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENVIRONMENT", "test")

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from syn_adapters.subscriptions.coordinator_service import SubscriptionServiceStatus
from syn_adapters.subscriptions.read_model_lag import (
    CheckpointState,
    ReadModelLag,
    measure_read_model_lag,
)
from syn_api.services import lifecycle
from syn_api.services.read_model_status import LIVE_LAG_THRESHOLD, judge_read_model_status

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = [pytest.mark.unit]

NOW = datetime(2026, 10, 8, 2, 0, tzinfo=UTC)
#: The reported deploy: workflow_executions 29,476 events behind a 40,939 head.
HEAD = 40_939
EXECUTIONS = "workflow_executions"
EVALS = "evals"
DETAILS = "workflow_execution_details"


def _lag(positions: dict[str, int], *, replaying: bool) -> ReadModelLag:
    return measure_read_model_lag(
        head_position=HEAD,
        checkpoints={
            name: CheckpointState(position=pos, updated_at=NOW) for name, pos in positions.items()
        },
        projection_names=list(positions),
        replaying=replaying,
        now=NOW,
    )


def _rebuilding_executions() -> ReadModelLag:
    return _lag({EXECUTIONS: HEAD - 29_476, EVALS: HEAD, DETAILS: HEAD}, replaying=True)


class TestJudgement:
    def test_progress_is_position_against_head_with_display_strings(self) -> None:
        status = judge_read_model_status(_rebuilding_executions(), EXECUTIONS)

        assert status.rebuilding is True
        # 11,463 / 40,939 = 28.0%: floored, from the checkpoint, not guessed.
        assert status.progress_pct == 28
        assert status.events_behind == 29_476
        assert status.progress_display == "28%"
        assert status.events_behind_display == "29,476 events behind"
        assert status.summary_display == (
            "Rebuilding execution history - 28% (29,476 events behind)."
        )

    def test_a_peer_at_the_head_is_not_rebuilding_while_another_replays(self) -> None:
        status = judge_read_model_status(_rebuilding_executions(), EVALS)

        assert status.rebuilding is False
        assert status.summary_display is None

    def test_ordinary_live_lag_is_not_a_rebuild(self) -> None:
        """A checkpoint a few events short mid-dispatch must not flash a banner."""
        lag = _lag({EXECUTIONS: HEAD - 3}, replaying=False)

        assert lag.lagging_projections  # it IS behind; the verdict is what filters it
        assert judge_read_model_status(lag, EXECUTIONS).rebuilding is False

    def test_far_behind_on_its_own_rebuild_track_is_a_rebuild(self) -> None:
        """#1318: one projection replays on its own track while the coordinator is live."""
        lag = _lag({EXECUTIONS: HEAD - LIVE_LAG_THRESHOLD - 1}, replaying=False)

        assert lag.is_catching_up is False
        assert judge_read_model_status(lag, EXECUTIONS).rebuilding is True

    def test_the_threshold_itself_is_still_live_lag(self) -> None:
        lag = _lag({EXECUTIONS: HEAD - LIVE_LAG_THRESHOLD}, replaying=False)

        assert judge_read_model_status(lag, EXECUTIONS).rebuilding is False

    def test_never_reads_100_percent_while_behind(self) -> None:
        lag = _lag({EXECUTIONS: HEAD - 1}, replaying=True)

        assert judge_read_model_status(lag, EXECUTIONS).progress_display == "99%"

    def test_unmeasurable_lag_is_not_a_rebuild(self) -> None:
        assert judge_read_model_status(None, EXECUTIONS).rebuilding is False


class _SubscriptionServiceStub:
    def __init__(self, lag: ReadModelLag) -> None:
        self._lag = lag

    def get_status(self) -> SubscriptionServiceStatus:
        return SubscriptionServiceStatus(running=True, projection_count=3, realtime_enabled=True)

    async def describe_read_model_lag(self) -> ReadModelLag:
        return self._lag

    async def describe_unapplied_starts(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_storage() -> Iterator[None]:
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    yield
    reset_storage()
    reset_projection_manager()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from syn_api.main import create_app

    original = lifecycle._state.subscription_service
    lifecycle._state.subscription_service = _SubscriptionServiceStub(_rebuilding_executions())  # type: ignore[assignment]  # stub
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
            yield c
    finally:
        lifecycle._state.subscription_service = original


@pytest.mark.anyio
class TestOnTheWire:
    async def test_health_lists_the_rebuilding_read_model_for_the_banner(
        self, client: AsyncClient
    ) -> None:
        body = json.loads((await client.get("/health")).text)

        rebuilding = body["subscription"]["rebuilding_read_models"]
        assert [entry["projection"] for entry in rebuilding] == [EXECUTIONS]
        assert rebuilding[0]["summary_display"] == (
            "Rebuilding execution history - 28% (29,476 events behind)."
        )

    async def test_the_execution_list_says_its_read_model_is_rebuilding(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/executions")
        assert response.status_code == 200

        status = json.loads(response.text)["read_model_status"]
        assert status["rebuilding"] is True
        assert status["projection"] == EXECUTIONS
        assert status["progress_display"] == "28%"

    async def test_the_eval_list_names_its_own_read_model_not_another(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/evals")
        assert response.status_code == 200

        status = json.loads(response.text)["read_model_status"]
        assert status == {
            "rebuilding": False,
            "projection": EVALS,
            "label_display": "evals",
            "progress_pct": None,
            "progress_display": None,
            "events_behind": 0,
            "events_behind_display": None,
            "summary_display": None,
        }
