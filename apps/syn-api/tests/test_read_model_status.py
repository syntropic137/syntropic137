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


def _lag(positions: dict[str, int], *, replaying: bool, head: int = HEAD) -> ReadModelLag:
    return measure_read_model_lag(
        head_position=head,
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

    def test_live_lag_beside_another_projections_replay_is_not_a_rebuild(self) -> None:
        """`is_catching_up` is true while ANY track replays; it says nothing of this one."""
        lag = _lag({EXECUTIONS: HEAD - 29_476, EVALS: HEAD - 3}, replaying=True)

        assert lag.is_catching_up is True
        assert judge_read_model_status(lag, EXECUTIONS).rebuilding is True
        assert judge_read_model_status(lag, EVALS).rebuilding is False

    def test_far_behind_on_its_own_rebuild_track_is_a_rebuild(self) -> None:
        """#1318: one projection replays on its own track while the coordinator is live."""
        lag = _lag({EXECUTIONS: HEAD - LIVE_LAG_THRESHOLD - 1}, replaying=False)

        assert lag.is_catching_up is False
        assert judge_read_model_status(lag, EXECUTIONS).rebuilding is True

    def test_the_threshold_itself_is_still_live_lag(self) -> None:
        lag = _lag({EXECUTIONS: HEAD - LIVE_LAG_THRESHOLD}, replaying=False)

        assert judge_read_model_status(lag, EXECUTIONS).rebuilding is False

    def test_never_reads_100_percent_while_behind(self) -> None:
        head = 200_000
        lag = _lag({EXECUTIONS: head - LIVE_LAG_THRESHOLD - 1}, replaying=True, head=head)

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


class _SwitchableLagStub(_SubscriptionServiceStub):
    """The coordinator answering with whatever lag the test sets next."""

    def set_lag(self, lag: ReadModelLag) -> None:
        self._lag = lag


@pytest.fixture
async def eval_detail_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, _SwitchableLagStub]]:
    from syn_api.main import create_app
    from syn_domain.testing.fake_revision_resolver import FakeRevisionResolver

    fake = FakeRevisionResolver(shas={("acme/app", "main"): "a" * 40})
    monkeypatch.setattr("syn_api.routes.evals.get_revision_resolver", lambda: fake)
    stub = _SwitchableLagStub(_lag({EXECUTIONS: HEAD, EVALS: HEAD, DETAILS: HEAD}, replaying=False))
    original = lifecycle._state.subscription_service
    lifecycle._state.subscription_service = stub  # type: ignore[assignment]  # stub
    try:
        async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
            yield c, stub
    finally:
        lifecycle._state.subscription_service = original


async def _seed_eval(client: AsyncClient) -> str:
    """Create an eval over HTTP and replay it into the eval read model."""
    from event_sourcing.client.memory import MemoryEventStoreClient
    from event_sourcing.stores.memory_checkpoint import MemoryCheckpointStore

    from syn_adapters.projections.manager import get_projection_manager
    from syn_adapters.storage.event_store_client import get_event_store_client
    from syn_domain.testing.stored_replay import replay

    response = await client.post(
        "/evals",
        json={
            "name": "Refactor baseline",
            "goal": "Does the refactor workflow keep tests green?",
            "baseline_repos": [{"repository": "acme/app", "requested_ref": "main"}],
            "tags": [],
        },
    )
    assert response.status_code == 201, response.text
    store_client = get_event_store_client()
    assert isinstance(store_client, MemoryEventStoreClient)
    await replay(store_client, MemoryCheckpointStore(), get_projection_manager().eval_list)
    return response.json()["eval_id"]


@pytest.mark.anyio
class TestEvalDetailOnTheWire:
    async def test_the_eval_detail_says_its_own_read_model_is_rebuilding_then_caught_up(
        self, eval_detail_client: tuple[AsyncClient, _SwitchableLagStub]
    ) -> None:
        client, coordinator = eval_detail_client
        eval_id = await _seed_eval(client)

        # Evals 20,470 behind; the execution read models are at the head.
        coordinator.set_lag(
            _lag({EXECUTIONS: HEAD, EVALS: HEAD - 20_470, DETAILS: HEAD}, replaying=True)
        )
        response = await client.get(f"/evals/{eval_id}")
        assert response.status_code == 200, response.text
        body = json.loads(response.text)
        assert body["eval_id"] == eval_id
        # 20,469 / 40,939 = 49.99%: floored, from the checkpoint.
        assert body["read_model_status"] == {
            "rebuilding": True,
            "projection": EVALS,
            "label_display": "evals",
            "progress_pct": 49,
            "progress_display": "49%",
            "events_behind": 20_470,
            "events_behind_display": "20,470 events behind",
            "summary_display": "Rebuilding evals - 49% (20,470 events behind).",
        }

        coordinator.set_lag(_lag({EXECUTIONS: HEAD, EVALS: HEAD, DETAILS: HEAD}, replaying=False))
        caught_up = json.loads((await client.get(f"/evals/{eval_id}")).text)["read_model_status"]
        assert caught_up["rebuilding"] is False
        assert caught_up["projection"] == EVALS
        assert caught_up["summary_display"] is None

    async def test_the_eval_detail_ignores_another_read_model_rebuilding(
        self, eval_detail_client: tuple[AsyncClient, _SwitchableLagStub]
    ) -> None:
        client, coordinator = eval_detail_client
        eval_id = await _seed_eval(client)

        coordinator.set_lag(_rebuilding_executions())
        status = json.loads((await client.get(f"/evals/{eval_id}")).text)["read_model_status"]
        assert status["projection"] == EVALS
        assert status["rebuilding"] is False
