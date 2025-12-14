#!/usr/bin/env python3
"""End-to-end test for tool token attribution.

This script validates the full flow:
1. Emit token_usage event with tool_details
2. Verify CostRecordedEvent has tool breakdown
3. Verify projection aggregates correctly
4. Verify API returns tool data

Usage:
    python scripts/e2e_tool_token_test.py
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

from aef_domain.contexts.costs.domain.read_models.session_cost import SessionCost
from aef_domain.contexts.costs.services.cost_calculator import CostCalculator
from aef_domain.contexts.costs.slices.session_cost.projection import SessionCostProjection


class InMemoryProjectionStore:
    """Simple in-memory store for testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict]] = {}

    async def save(self, projection_name: str, key: str, data: dict) -> None:
        if projection_name not in self._data:
            self._data[projection_name] = {}
        self._data[projection_name][key] = data

    async def get(self, projection_name: str, key: str) -> dict | None:
        return self._data.get(projection_name, {}).get(key)

    async def query(
        self,
        projection_name: str,
        filters: dict | None = None,
        order_by: str | None = None,  # noqa: ARG002 - match protocol signature
    ) -> list[dict]:
        results = list(self._data.get(projection_name, {}).values())
        if filters:
            results = [r for r in results if all(r.get(k) == v for k, v in filters.items())]
        return results

    async def get_all(self, projection_name: str) -> list[dict]:
        return list(self._data.get(projection_name, {}).values())


class CollectedEvents:
    """Collector for emitted events."""

    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, event) -> None:
        self.events.append(event)


async def test_tool_token_e2e() -> None:
    """Test the full tool token attribution flow."""
    print("\n🧪 E2E Test: Tool Token Attribution\n")
    print("=" * 60)

    # Setup
    store = InMemoryProjectionStore()
    projection = SessionCostProjection(store)
    collector = CollectedEvents()
    calculator = CostCalculator(emitter=collector)

    session_id = "e2e-test-session"

    # Step 1: Simulate a token_usage event with tool_details
    print("\n📥 Step 1: Emit token_usage event with tool_details")
    token_event = {
        "session_id": session_id,
        "execution_id": "e2e-exec",
        "model": "claude-sonnet-4-20250514",
        "input_tokens": 5000,
        "output_tokens": 2000,
        "timestamp": "2025-01-01T12:00:00Z",
        "tool_details": [
            {"name": "Read", "input_size": 50, "result_size": 4000},  # Large file read
            {"name": "Write", "input_size": 2000, "result_size": 30},  # File write
            {"name": "Shell", "input_size": 100, "result_size": 500},  # Command execution
        ],
    }

    cost_event = await calculator.on_token_usage(token_event)
    assert cost_event is not None, "CostRecordedEvent should be created"
    print(f"   ✅ CostRecordedEvent created: cost=${cost_event.amount_usd}")

    # Step 2: Verify tool_token_breakdown in the event
    print("\n📊 Step 2: Verify tool_token_breakdown in CostRecordedEvent")
    breakdown = cost_event.tool_token_breakdown
    assert "Read" in breakdown, "Read tool should be in breakdown"
    assert "Write" in breakdown, "Write tool should be in breakdown"
    assert "Shell" in breakdown, "Shell tool should be in breakdown"

    print("   Tool breakdown:")
    for tool, tokens in breakdown.items():
        print(f"     - {tool}: tool_use={tokens['tool_use']}, tool_result={tokens['tool_result']}")

    # Step 3: Apply to projection and verify aggregation
    print("\n🗄️ Step 3: Apply to projection and verify aggregation")
    event_dict = cost_event.to_dict()
    await projection.on_cost_recorded(event_dict)

    session_cost = await projection.get_session_cost(session_id)
    assert session_cost is not None, "SessionCost should be created"
    assert session_cost.tokens_by_tool is not None, "tokens_by_tool should be populated"

    print(f"   Session cost: ${session_cost.total_cost_usd}")
    print(f"   Tokens by tool: {session_cost.tokens_by_tool}")

    # Verify token counts make sense
    read_tokens = session_cost.tokens_by_tool.get("Read", 0)
    write_tokens = session_cost.tokens_by_tool.get("Write", 0)
    shell_tokens = session_cost.tokens_by_tool.get("Shell", 0)

    assert read_tokens > 500, f"Read should have many tokens (got {read_tokens})"
    assert write_tokens > 500, f"Write should have many tokens (got {write_tokens})"
    assert shell_tokens > 100, f"Shell should have some tokens (got {shell_tokens})"

    print("   ✅ Token counts validated:")
    print(f"     - Read: {read_tokens} tokens")
    print(f"     - Write: {write_tokens} tokens")
    print(f"     - Shell: {shell_tokens} tokens")

    # Step 4: Simulate second API call with more tool usage
    print("\n📥 Step 4: Add second token_usage event (aggregation test)")
    token_event_2 = {
        "session_id": session_id,
        "execution_id": "e2e-exec",
        "model": "claude-sonnet-4-20250514",
        "input_tokens": 3000,
        "output_tokens": 1000,
        "timestamp": "2025-01-01T12:01:00Z",
        "tool_details": [
            {"name": "Read", "input_size": 50, "result_size": 2000},  # Another read
            {"name": "Grep", "input_size": 100, "result_size": 300},  # New tool
        ],
    }

    cost_event_2 = await calculator.on_token_usage(token_event_2)
    assert cost_event_2 is not None
    await projection.on_cost_recorded(cost_event_2.to_dict())

    # Verify aggregation
    session_cost = await projection.get_session_cost(session_id)
    assert session_cost is not None

    print(f"   Updated tokens by tool: {session_cost.tokens_by_tool}")

    # Read should have accumulated
    assert session_cost.tokens_by_tool["Read"] > read_tokens, "Read tokens should accumulate"
    assert "Grep" in session_cost.tokens_by_tool, "Grep should be added"

    print("   ✅ Aggregation verified:")
    print(f"     - Read increased: {read_tokens} → {session_cost.tokens_by_tool['Read']}")
    print(f"     - New tool Grep: {session_cost.tokens_by_tool['Grep']}")

    # Step 5: Verify serialization roundtrip
    print("\n📦 Step 5: Verify serialization roundtrip")
    session_dict = session_cost.to_dict()
    assert "tokens_by_tool" in session_dict, "tokens_by_tool should be in dict"

    # Reconstruct
    reconstructed = SessionCost.from_dict(session_dict)
    assert reconstructed.tokens_by_tool == session_cost.tokens_by_tool, "Should roundtrip correctly"
    print("   ✅ Serialization roundtrip successful")

    # Summary
    print("\n" + "=" * 60)
    print("✅ All E2E tests passed!")
    print("\nFinal session summary:")
    print(f"  Session ID: {session_cost.session_id}")
    print(f"  Total cost: ${session_cost.total_cost_usd}")
    print(f"  Total tokens: {session_cost.total_tokens}")
    print(f"  Turns: {session_cost.turns}")
    print(f"  Tools used: {list(session_cost.tokens_by_tool.keys())}")
    print()


async def test_api_response_format() -> None:
    """Test that API response format is correct."""
    print("\n🧪 E2E Test: API Response Format\n")
    print("=" * 60)

    # Create a SessionCost with tool token data
    session_cost = SessionCost(
        session_id="api-test",
        total_cost_usd=Decimal("0.50"),
        token_cost_usd=Decimal("0.48"),
        compute_cost_usd=Decimal("0.02"),
        input_tokens=10000,
        output_tokens=5000,
        tokens_by_tool={"Write": 8000, "Read": 5000, "Shell": 2000},
        cost_by_tool_tokens={
            "Write": Decimal("0.25"),
            "Read": Decimal("0.15"),
            "Shell": Decimal("0.08"),
        },
    )

    # Convert to dict (simulating API serialization)
    response = session_cost.to_dict()

    print("API Response structure:")
    print(f"  session_id: {response['session_id']}")
    print(f"  total_cost_usd: {response['total_cost_usd']}")
    print(f"  tokens_by_tool: {response['tokens_by_tool']}")
    print(f"  cost_by_tool_tokens: {response['cost_by_tool_tokens']}")

    # Verify format
    assert isinstance(response["tokens_by_tool"], dict), "tokens_by_tool should be dict"
    assert all(
        isinstance(v, int) for v in response["tokens_by_tool"].values()
    ), "token counts should be int"

    assert isinstance(response["cost_by_tool_tokens"], dict), "cost_by_tool_tokens should be dict"
    assert all(
        isinstance(v, str) for v in response["cost_by_tool_tokens"].values()
    ), "costs should be string"

    print("\n✅ API response format verified")
    print()


if __name__ == "__main__":
    asyncio.run(test_tool_token_e2e())
    asyncio.run(test_api_response_format())
