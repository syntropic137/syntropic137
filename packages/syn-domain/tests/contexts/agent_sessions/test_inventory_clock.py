"""Clock observations are immutable across retries and aggregate replay."""

from datetime import UTC, datetime, timedelta

import pytest

from syn_domain.contexts.agent_sessions import InventoryClockAggregate, ObserveInventoryClockCommand

pytestmark = pytest.mark.unit


def test_clock_replay_and_retry_preserve_one_observation() -> None:
    command = ObserveInventoryClockCommand(aggregate_id="tick", observed_at=datetime.now(UTC))
    clock = InventoryClockAggregate()
    clock.observe(command)
    clock.observe(command)
    events = clock.get_uncommitted_events()
    assert len(events) == 1
    assert events[0].event.observed_at == command.observed_at
    replayed = InventoryClockAggregate()
    replayed.rehydrate(events)
    replayed.observe(command)
    assert not replayed.get_uncommitted_events()
    with pytest.raises(ValueError, match="identity reused"):
        replayed.observe(
            command.model_copy(update={"observed_at": command.observed_at + timedelta(seconds=1)})
        )
