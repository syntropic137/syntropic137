"""A cancel response says whether the cancel has taken effect yet (#1062).

Cancelling a started execution queues a signal that the executor acts on
later, so the response's `state` is the state before the cancel: `running`.
Nothing in the response said so, and a caller re-reading once saw `running`
and reported the cancel as refused. `applied` is what tells the two apart.

Driven through #1557's world: the real cancel route, controller and signal
queue over one store.
"""

from __future__ import annotations

import pytest
from test_1557_one_execution_budget import (  # pyright: ignore[reportMissingImports]
    _cancel,  # pyright: ignore[reportPrivateUsage]
    _release_everything,  # pyright: ignore[reportPrivateUsage]
    _two_running_one_queued,  # pyright: ignore[reportPrivateUsage]
    _World,  # pyright: ignore[reportPrivateUsage]
)

from syn_api.main import app

pytestmark = pytest.mark.unit


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> _World:
    return _World(monkeypatch)


class TestACancelOfARunningExecution:
    async def test_is_queued_not_applied(self, world: _World) -> None:
        running, _ = await _two_running_one_queued(world)

        response = await _cancel(running[0])

        assert response.applied is False
        assert response.state == "running"
        assert response.message == "Cancel signal queued"
        # What the CLI reads: the field reaches the wire, not just the model.
        assert response.model_dump(mode="json")["applied"] is False
        await _release_everything(world)


class TestACancelThatWithdrawsAQueuedStart:
    async def test_is_applied_and_already_cancelled(self, world: _World) -> None:
        _, queued = await _two_running_one_queued(world)

        response = await _cancel(queued)

        assert response.applied is True
        assert response.state == "cancelled"
        assert response.model_dump(mode="json")["applied"] is True
        await _release_everything(world)


class TestTheContract:
    def test_applied_is_required_and_state_says_it_may_be_stale(self) -> None:
        """The OpenAPI spec is what generates the CLI's types and the API docs."""
        schema = app.openapi()["components"]["schemas"]["ControlResponse"]

        assert "applied" in schema["required"]
        assert schema["properties"]["applied"]["type"] == "boolean"
        assert "BEFORE" in schema["properties"]["state"]["description"]
