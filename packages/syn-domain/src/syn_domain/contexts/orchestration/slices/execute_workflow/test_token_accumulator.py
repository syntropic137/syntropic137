"""Tests for TokenAccumulator."""

from __future__ import annotations

from syn_domain.contexts.orchestration.slices.execute_workflow.TokenAccumulator import (
    TokenAccumulator,
)


class TestTokenAccumulator:
    def test_initial_state(self) -> None:
        acc = TokenAccumulator()
        assert acc.input_tokens == 0
        assert acc.output_tokens == 0
        assert acc.cache_creation_tokens == 0
        assert acc.cache_read_tokens == 0
        assert acc.total_tokens == 0

    def test_record_accumulates(self) -> None:
        acc = TokenAccumulator()
        acc.record(100, 200)
        acc.record(50, 100)
        assert acc.input_tokens == 150
        assert acc.output_tokens == 300
        assert acc.total_tokens == 450

    def test_record_cache_tokens(self) -> None:
        acc = TokenAccumulator()
        acc.record(100, 200, cache_creation_tokens=50, cache_read_tokens=30)
        acc.record(0, 0, cache_creation_tokens=20, cache_read_tokens=10)
        assert acc.cache_creation_tokens == 70
        assert acc.cache_read_tokens == 40

    def test_total_tokens_includes_cache(self) -> None:
        acc = TokenAccumulator()
        acc.record(100, 200, cache_creation_tokens=50, cache_read_tokens=30)
        assert acc.total_tokens == 380
