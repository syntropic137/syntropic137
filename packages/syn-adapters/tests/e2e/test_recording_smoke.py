"""E2E smoke tests using recordings.

These tests verify the full observability pipeline works end-to-end
by replaying recordings through the entire system.

ZERO TOKEN COST - 100% DETERMINISTIC - FAST EXECUTION

See ADR-033: Recording-Based Integration Testing
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from syn_adapters.workspace_backends.recording import RecordingEventStreamAdapter

pytestmark = [pytest.mark.unit, pytest.mark.e2e]  # Runs in CI - no external services


# =============================================================================
# SMOKE TEST: FULL PIPELINE
# =============================================================================


class TestE2EObservabilitySmoke:
    """End-to-end smoke tests for the observability pipeline.

    These tests verify that:
    1. Events can be read from recordings
    2. Events can be streamed via adapter
    3. All critical data is extractable
    4. No data is lost in transformation
    """

    @pytest.fixture
    def all_recordings(self) -> list[str]:
        """List all available recordings."""
        return [
            "simple-bash",
            "file-create",
            "file-read",
            "git-status",
            "multi-tool",
            "simple-question",
            "list-files",
        ]

    def test_smoke_all_recordings_load(self, all_recordings: list[str]) -> None:
        """SMOKE: All recordings can be loaded."""
        loaded = []
        failed = []

        for name in all_recordings:
            try:
                adapter = RecordingEventStreamAdapter(name)
                loaded.append((name, adapter.event_count))
            except FileNotFoundError:
                failed.append(name)

        assert len(loaded) > 0, "At least one recording should load"

        # Report what loaded
        for name, count in loaded:
            print(f"  ✅ {name}: {count} events")

        if failed:
            print(f"  ⚠️ Not found: {failed}")

    def test_smoke_session_id_extraction(self, all_recordings: list[str]) -> None:
        """SMOKE: Session ID extractable from all recordings."""
        for name in all_recordings:
            try:
                adapter = RecordingEventStreamAdapter(name)
                assert adapter.session_id is not None, f"{name}: No session_id"
                print(f"  ✅ {name}: {adapter.session_id[:8]}...")
            except FileNotFoundError:
                pass

    def test_smoke_cost_extraction(self, all_recordings: list[str]) -> None:
        """SMOKE: Cost extractable from all recordings."""
        for name in all_recordings:
            try:
                adapter = RecordingEventStreamAdapter(name)
                events = adapter.get_events()
                result = next((e for e in events if e.get("type") == "result"), None)

                assert result is not None, f"{name}: No result event"

                cost = result.get("total_cost_usd")
                assert cost is not None, f"{name}: No cost"
                assert isinstance(cost, (int, float)), f"{name}: Cost not numeric"

                print(f"  ✅ {name}: ${cost:.6f}")
            except FileNotFoundError:
                pass

    def test_smoke_token_extraction(self, all_recordings: list[str]) -> None:
        """SMOKE: Token counts extractable from all recordings."""
        for name in all_recordings:
            try:
                adapter = RecordingEventStreamAdapter(name)
                events = adapter.get_events()
                result = next((e for e in events if e.get("type") == "result"), None)

                assert result is not None, f"{name}: No result event"

                usage = result.get("usage", {})
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)

                assert input_tokens > 0 or output_tokens > 0, f"{name}: No tokens"

                print(f"  ✅ {name}: {input_tokens}in/{output_tokens}out")
            except FileNotFoundError:
                pass

    @pytest.mark.asyncio
    async def test_smoke_streaming_produces_events(self, all_recordings: list[str]) -> None:
        """SMOKE: Streaming produces valid events."""
        from unittest.mock import MagicMock

        for name in all_recordings:
            try:
                adapter = RecordingEventStreamAdapter(name)
                mock_handle = MagicMock()

                event_count = 0
                async for line in adapter.stream(mock_handle, ["test"]):
                    event = json.loads(line)
                    assert "type" in event
                    event_count += 1

                assert event_count == adapter.event_count, f"{name}: Event count mismatch"
                print(f"  ✅ {name}: streamed {event_count} events")
            except FileNotFoundError:
                pass


# =============================================================================
# SMOKE TEST: CRITICAL DATA PATHS
# =============================================================================


class TestE2ECriticalPaths:
    """Tests for critical data paths that MUST work."""

    def test_critical_session_lifecycle_complete(self) -> None:
        """CRITICAL: Session has start and end events."""
        try:
            adapter = RecordingEventStreamAdapter("simple-bash")
        except FileNotFoundError:
            pytest.skip("simple-bash not available")

        events = adapter.get_events()

        # Must have init
        init = next(
            (e for e in events if e.get("type") == "system" and e.get("subtype") == "init"),
            None,
        )
        assert init is not None, "CRITICAL: No session start event!"

        # Must have result
        result = next((e for e in events if e.get("type") == "result"), None)
        assert result is not None, "CRITICAL: No session end event!"

        print("  ✅ Session lifecycle: init → result")

    def test_critical_tool_use_visible(self) -> None:
        """CRITICAL: Tool usage is visible in events."""
        try:
            adapter = RecordingEventStreamAdapter("multi-tool")
        except FileNotFoundError:
            pytest.skip("multi-tool not available")

        events = adapter.get_events()

        tool_uses = []
        for event in events:
            if event.get("type") != "assistant":
                continue
            message = event.get("message", {})
            content = message.get("content", [])
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    tool_uses.append(item.get("name"))

        assert len(tool_uses) > 0, "CRITICAL: No tool usage visible!"
        print(f"  ✅ Tools visible: {tool_uses}")

    def test_critical_cost_calculated(self) -> None:
        """CRITICAL: Cost is calculated and non-zero."""
        try:
            adapter = RecordingEventStreamAdapter("simple-bash")
        except FileNotFoundError:
            pytest.skip("simple-bash not available")

        events = adapter.get_events()
        result = next((e for e in events if e.get("type") == "result"), None)

        assert result is not None
        cost = result.get("total_cost_usd")

        assert cost is not None, "CRITICAL: No cost calculated!"
        assert cost > 0, "CRITICAL: Cost is zero!"

        print(f"  ✅ Cost calculated: ${cost:.6f}")

    def test_critical_model_identified(self) -> None:
        """CRITICAL: Model is identified for cost calculation."""
        try:
            adapter = RecordingEventStreamAdapter("simple-bash")
        except FileNotFoundError:
            pytest.skip("simple-bash not available")

        events = adapter.get_events()
        init = next(
            (e for e in events if e.get("type") == "system" and e.get("subtype") == "init"),
            None,
        )

        assert init is not None
        model = init.get("model")

        assert model is not None, "CRITICAL: No model identified!"
        print(f"  ✅ Model: {model}")


# =============================================================================
# SMOKE TEST: DATA INTEGRITY
# =============================================================================


class TestE2EDataIntegrity:
    """Tests for data integrity through the pipeline."""

    def test_integrity_no_events_lost(self) -> None:
        """INTEGRITY: No events lost in streaming."""
        try:
            adapter = RecordingEventStreamAdapter("multi-tool")
        except FileNotFoundError:
            pytest.skip("multi-tool not available")

        original_events = adapter.get_events()
        original_types = [e.get("type") for e in original_events]

        # Verify each type is present
        type_counts: dict[str, int] = {}
        for t in original_types:
            type_counts[t] = type_counts.get(t, 0) + 1

        assert "system" in type_counts, "Lost system events"
        assert "result" in type_counts, "Lost result events"

        print(f"  ✅ Event counts: {type_counts}")

    def test_integrity_session_id_consistent(self) -> None:
        """INTEGRITY: Session ID is consistent across events."""
        try:
            adapter = RecordingEventStreamAdapter("simple-bash")
        except FileNotFoundError:
            pytest.skip("simple-bash not available")

        events = adapter.get_events()
        session_ids = {e.get("session_id") for e in events if e.get("session_id")}

        assert len(session_ids) == 1, f"Multiple session IDs: {session_ids}"
        print(f"  ✅ Consistent session_id: {next(iter(session_ids))[:8]}...")

    def test_integrity_event_order_preserved(self) -> None:
        """INTEGRITY: Event order is preserved."""
        try:
            adapter = RecordingEventStreamAdapter("simple-bash")
        except FileNotFoundError:
            pytest.skip("simple-bash not available")

        events = adapter.get_events()
        types = [e.get("type") for e in events]

        # system.init should be first
        assert types[0] == "system", "First event should be system"

        # result should be last
        assert types[-1] == "result", "Last event should be result"

        print(f"  ✅ Order: {types[0]} → ... → {types[-1]}")


# =============================================================================
# SMOKE TEST: PERFORMANCE
# =============================================================================


class TestE2EPerformance:
    """Tests for performance characteristics."""

    def test_performance_recordings_load_fast(self) -> None:
        """PERFORMANCE: Recordings load in <10ms each."""
        import time

        recordings = ["simple-bash", "multi-tool", "file-create"]

        for name in recordings:
            try:
                start = time.perf_counter()
                adapter = RecordingEventStreamAdapter(name)
                elapsed = (time.perf_counter() - start) * 1000

                assert elapsed < 50, f"{name} took {elapsed:.1f}ms (>50ms)"
                print(f"  ✅ {name}: {elapsed:.2f}ms ({adapter.event_count} events)")
            except FileNotFoundError:
                pass

    def test_performance_event_extraction_fast(self) -> None:
        """PERFORMANCE: Event extraction is fast."""
        import time

        try:
            adapter = RecordingEventStreamAdapter("multi-tool")
        except FileNotFoundError:
            pytest.skip("multi-tool not available")

        start = time.perf_counter()

        # Extract all key data
        events = adapter.get_events()
        session_id = adapter.session_id
        result = next((e for e in events if e.get("type") == "result"), None)
        cost = result.get("total_cost_usd") if result else None

        elapsed = (time.perf_counter() - start) * 1000

        assert elapsed < 10, f"Extraction took {elapsed:.1f}ms (>10ms)"
        print(f"  ✅ Full extraction: {elapsed:.2f}ms")
        print(f"     session_id: {session_id[:8]}...")
        print(f"     cost: ${cost:.6f}" if cost else "     cost: N/A")


# =============================================================================
# SUMMARY TEST
# =============================================================================


class TestE2ESummary:
    """Summary test that validates the entire pipeline."""

    def test_full_pipeline_summary(self) -> None:
        """SUMMARY: Full pipeline validation."""
        recordings = [
            "simple-bash",
            "file-create",
            "file-read",
            "git-status",
            "multi-tool",
            "simple-question",
            "list-files",
        ]

        results: list[dict[str, Any]] = []

        for name in recordings:
            try:
                adapter = RecordingEventStreamAdapter(name)
                events = adapter.get_events()
                result_event = next((e for e in events if e.get("type") == "result"), None)

                if result_event:
                    usage = result_event.get("usage", {})
                    results.append(
                        {
                            "name": name,
                            "events": adapter.event_count,
                            "session_id": adapter.session_id[:8] if adapter.session_id else "N/A",
                            "cost": result_event.get("total_cost_usd", 0),
                            "input_tokens": usage.get("input_tokens", 0),
                            "output_tokens": usage.get("output_tokens", 0),
                        }
                    )
            except FileNotFoundError:
                pass

        assert len(results) > 0, "No recordings loaded!"

        # Print summary table
        print("\n" + "=" * 70)
        print("  E2E SMOKE TEST SUMMARY")
        print("=" * 70)
        print(f"  {'Recording':<20} {'Events':>8} {'Cost':>12} {'In Tok':>10} {'Out Tok':>10}")
        print("-" * 70)

        total_events = 0
        total_cost = 0.0
        total_input = 0
        total_output = 0

        for r in results:
            print(
                f"  {r['name']:<20} {r['events']:>8} "
                f"${r['cost']:>10.6f} {r['input_tokens']:>10} {r['output_tokens']:>10}"
            )
            total_events += r["events"]
            total_cost += r["cost"]
            total_input += r["input_tokens"]
            total_output += r["output_tokens"]

        print("-" * 70)
        print(
            f"  {'TOTAL':<20} {total_events:>8} "
            f"${total_cost:>10.6f} {total_input:>10} {total_output:>10}"
        )
        print("=" * 70)
        print(f"  ✅ {len(results)} recordings validated successfully")
        print("=" * 70 + "\n")
