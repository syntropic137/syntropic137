#!/usr/bin/env python3
import asyncio

from cost_projection import CostProjection
from observability_writer import ObservabilityWriter


async def test_projection():
    print("🔍 Testing Cost Projection...")

    # Write test data
    writer = ObservabilityWriter("postgresql://test:test@timescale-test:5432/obs_test")
    await writer.initialize()

    session_id = "test-session-cost"

    # Simulate agent execution with realistic token counts
    # Turn 1: Initial context
    await writer.record_observation(
        session_id=session_id,
        observation_type="token_usage",
        execution_id="test-exec",
        data={
            "input_tokens": 10000,
            "output_tokens": 2000,
            "cache_creation_tokens": 5000,
            "cache_read_tokens": 1000,
        },
    )

    # Turn 2: Cached context
    await writer.record_observation(
        session_id=session_id,
        observation_type="token_usage",
        execution_id="test-exec",
        data={
            "input_tokens": 5000,
            "output_tokens": 1500,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 8000,
        },
    )

    # Turn 3: Final output
    await writer.record_observation(
        session_id=session_id,
        observation_type="token_usage",
        execution_id="test-exec",
        data={
            "input_tokens": 3000,
            "output_tokens": 1000,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 12000,
        },
    )

    # Simulate 15 tool calls
    for i in range(15):
        await writer.record_observation(
            session_id=session_id,
            observation_type="tool_completed",
            execution_id="test-exec",
            data={
                "tool_name": "bash" if i % 2 == 0 else "Read",
                "tool_use_id": f"toolu_{i}",
                "output": f"Result {i}",
                "duration_ms": 100 + i * 10,
            },
        )

    await writer.close()
    print("✅ Test data written")

    # Query projection
    projection = CostProjection("postgresql://test:test@timescale-test:5432/obs_test")
    await projection.initialize()

    result = await projection.calculate_session_cost(session_id)

    print("\n📊 Session Cost Summary:")
    print(f"  Input tokens: {result['input_tokens']:,}")
    print(f"  Output tokens: {result['output_tokens']:,}")
    print(f"  Cache creation tokens: {result['cache_creation_tokens']:,}")
    print(f"  Cache read tokens: {result['cache_read_tokens']:,}")
    print(f"  Tool calls: {result['tool_calls']}")
    print(f"  Total cost: ${result['total_cost_usd']:.4f}")

    # Assertions
    assert result["input_tokens"] == 18000, (
        f"Input tokens mismatch: expected 18000, got {result['input_tokens']}"
    )
    assert result["output_tokens"] == 4500, (
        f"Output tokens mismatch: expected 4500, got {result['output_tokens']}"
    )
    assert result["cache_creation_tokens"] == 5000, (
        f"Cache creation mismatch: expected 5000, got {result['cache_creation_tokens']}"
    )
    assert result["cache_read_tokens"] == 21000, (
        f"Cache read mismatch: expected 21000, got {result['cache_read_tokens']}"
    )
    assert result["tool_calls"] == 15, (
        f"Tool calls mismatch: expected 15, got {result['tool_calls']}"
    )
    assert result["total_cost_usd"] > 0, "Cost should be > 0"

    # Validate cost calculation
    # Manual calculation:
    # Input: 18000 * $0.000003 = $0.054
    # Output: 4500 * $0.000015 = $0.0675
    # Cache creation: 5000 * $0.00000375 = $0.01875
    # Cache read: 21000 * $0.0000003 = $0.0063
    # Total: $0.14655
    expected_cost = 0.14655
    assert abs(result["total_cost_usd"] - expected_cost) < 0.0001, (
        f"Cost calculation error: expected ${expected_cost:.4f}, got ${result['total_cost_usd']:.4f}"
    )
    print(
        f"✅ Cost calculation verified: ${result['total_cost_usd']:.4f} matches expected ${expected_cost:.4f}"
    )

    await projection.close()
    print("\n🎉 Projection tests passed!")


if __name__ == "__main__":
    asyncio.run(test_projection())
