"""Tests for PollerState adaptive interval state machine."""

from __future__ import annotations

from syn_domain.contexts.github.slices.event_pipeline.poller_state import (
    PollerMode,
    PollerState,
)


class TestPollerModeTransitions:
    def test_starts_in_active_polling(self) -> None:
        state = PollerState()
        assert state.mode == PollerMode.ACTIVE_POLLING

    def test_transitions_to_safety_net_when_healthy(self) -> None:
        state = PollerState()
        state.update_mode(webhook_stale=False)
        assert state.mode == PollerMode.SAFETY_NET

    def test_transitions_to_active_when_stale(self) -> None:
        state = PollerState()
        state.update_mode(webhook_stale=False)
        assert state.mode == PollerMode.SAFETY_NET

        state.update_mode(webhook_stale=True)
        assert state.mode == PollerMode.ACTIVE_POLLING

    def test_transition_resets_errors(self) -> None:
        state = PollerState()
        state.record_error()
        state.record_error()
        assert state.consecutive_errors == 2

        state.update_mode(webhook_stale=False)  # transition
        assert state.consecutive_errors == 0

    def test_no_transition_keeps_errors(self) -> None:
        state = PollerState()
        state.record_error()
        state.update_mode(webhook_stale=True)  # same mode
        assert state.consecutive_errors == 1


class TestPollerInterval:
    def test_active_uses_base_interval(self) -> None:
        state = PollerState(base_interval=60.0, safety_interval=300.0)
        assert state.current_interval == 60.0

    def test_safety_net_uses_safety_interval(self) -> None:
        state = PollerState(base_interval=60.0, safety_interval=300.0)
        state.update_mode(webhook_stale=False)
        assert state.current_interval == 300.0

    def test_backoff_doubles_on_error(self) -> None:
        state = PollerState(base_interval=60.0)
        state.record_error()
        assert state.current_interval == 120.0  # 60 * 2^1

        state.record_error()
        assert state.current_interval == 240.0  # 60 * 2^2

    def test_backoff_capped_at_max(self) -> None:
        state = PollerState(base_interval=60.0, max_backoff=600.0)
        for _ in range(10):
            state.record_error()
        assert state.current_interval == 600.0

    def test_success_resets_backoff(self) -> None:
        state = PollerState(base_interval=60.0)
        state.record_error()
        state.record_error()
        assert state.current_interval == 240.0

        state.record_success()
        assert state.current_interval == 60.0
        assert state.consecutive_errors == 0
