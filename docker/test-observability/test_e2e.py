#!/usr/bin/env python3
"""
End-to-End observability test.
Validates the complete flow: Agent → Writer → TimescaleDB → Projection → Cost Calculation
"""
import asyncio

from cost_projection import CostProjection
from observability_writer import ObservabilityWriter
from simulated_agent import SimulatedAgent


async def test_e2e():
    print("="*70)
    print("🧪 E2E OBSERVABILITY TEST")
    print("="*70)
    print("\nValidating: Agent → Writer → TimescaleDB → Projection → Cost\n")

    # Initialize writer
    writer = ObservabilityWriter(
        'postgresql://test:test@timescale-test:5432/obs_test'
    )
    await writer.initialize()
    print("✅ Step 1: ObservabilityWriter initialized")

    # Run simulated agent
    agent = SimulatedAgent(writer)
    session_id = 'e2e-test-session'
    execution_id = 'e2e-test-execution'

    await agent.run_task(session_id, execution_id, "Create a GitHub PR")
    print("\n✅ Step 2: Simulated agent execution complete")

    await writer.close()

    # Validate results with CostProjection
    print("\n" + "="*70)
    print("📊 VALIDATING RESULTS")
    print("="*70)

    projection = CostProjection(
        'postgresql://test:test@timescale-test:5432/obs_test'
    )
    await projection.initialize()

    result = await projection.calculate_session_cost(session_id)

    print("\n📈 Session Metrics:")
    print(f"  • Input tokens: {result['input_tokens']:,}")
    print(f"  • Output tokens: {result['output_tokens']:,}")
    print(f"  • Cache creation: {result['cache_creation_tokens']:,}")
    print(f"  • Cache read: {result['cache_read_tokens']:,}")
    print(f"  • Tool calls: {result['tool_calls']}")
    print(f"  • Total cost: ${result['total_cost_usd']:.4f}")

    # Expected values (from SimulatedAgent logic)
    # Turn 1: 15000 in, 2000 out, 8000 cache_create, 0 cache_read
    # Turn 2: 5000 in, 3000 out, 0 cache_create, 12000 cache_read
    # Turn 3: 3000 in, 1500 out, 0 cache_create, 10000 cache_read
    # Total: 23000 in, 6500 out, 8000 cache_create, 22000 cache_read
    # Tools: 6 (2 per turn x 3 turns)

    print("\n🔍 Validation:")

    # Assertions
    errors = []

    if result['input_tokens'] != 23000:
        errors.append(f"Input tokens: expected 23000, got {result['input_tokens']}")
    else:
        print("  ✓ Input tokens: 23,000")

    if result['output_tokens'] != 6500:
        errors.append(f"Output tokens: expected 6500, got {result['output_tokens']}")
    else:
        print("  ✓ Output tokens: 6,500")

    if result['cache_creation_tokens'] != 8000:
        errors.append(f"Cache creation: expected 8000, got {result['cache_creation_tokens']}")
    else:
        print("  ✓ Cache creation: 8,000")

    if result['cache_read_tokens'] != 22000:
        errors.append(f"Cache read: expected 22000, got {result['cache_read_tokens']}")
    else:
        print("  ✓ Cache read: 22,000")

    if result['tool_calls'] != 6:
        errors.append(f"Tool calls: expected 6, got {result['tool_calls']}")
    else:
        print("  ✓ Tool calls: 6")

    if result['total_cost_usd'] <= 0:
        errors.append(f"Cost should be > 0, got {result['total_cost_usd']}")
    else:
        print(f"  ✓ Total cost: ${result['total_cost_usd']:.4f}")

    # Verify cost calculation manually
    # Input: 23000 * $0.000003 = $0.069
    # Output: 6500 * $0.000015 = $0.0975
    # Cache creation: 8000 * $0.00000375 = $0.03
    # Cache read: 22000 * $0.0000003 = $0.0066
    # Total: $0.2031
    expected_cost = 0.2031
    if abs(result['total_cost_usd'] - expected_cost) > 0.0001:
        errors.append(f"Cost calculation: expected ${expected_cost:.4f}, got ${result['total_cost_usd']:.4f}")
    else:
        print(f"  ✓ Cost matches: ${expected_cost:.4f}")

    await projection.close()

    print("\n" + "="*70)
    if errors:
        print("❌ E2E TEST FAILED")
        print("="*70)
        for error in errors:
            print(f"  ✗ {error}")
        exit(1)
    else:
        print("🎉 E2E TEST PASSED!")
        print("="*70)
        print("\n✅ All components validated:")
        print("  • TimescaleDB hypertable + compression")
        print("  • ObservabilityWriter (high-throughput writes)")
        print("  • CostProjection (accurate cost calculation)")
        print("  • Simulated agent (realistic observation patterns)")
        print("\n🚀 Ready to integrate into production system!")


if __name__ == '__main__':
    asyncio.run(test_e2e())
