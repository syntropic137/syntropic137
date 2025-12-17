#!/usr/bin/env python3
import asyncio
import time

from observability_writer import ObservabilityWriter


async def test_writer():
    print("🔍 Testing ObservabilityWriter...")

    writer = ObservabilityWriter("postgresql://test:test@timescale-test:5432/obs_test")
    await writer.initialize()
    print("✅ Writer initialized")

    # Test 1: Token usage
    await writer.record_observation(
        session_id="test-session-1",
        observation_type="token_usage",
        execution_id="test-exec-1",
        data={
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_creation_tokens": 100,
            "cache_read_tokens": 50,
        },
    )
    print("✅ Token usage recorded")

    # Test 2: Tool started
    await writer.record_observation(
        session_id="test-session-1",
        observation_type="tool_started",
        execution_id="test-exec-1",
        data={
            "tool_name": "bash",
            "tool_use_id": "toolu_123",
            "input": {"command": 'echo "Hello World"'},
        },
    )
    print("✅ Tool started recorded")

    # Test 3: Tool completed
    await writer.record_observation(
        session_id="test-session-1",
        observation_type="tool_completed",
        execution_id="test-exec-1",
        data={
            "tool_name": "bash",
            "tool_use_id": "toolu_123",
            "output": "Hello World",
            "duration_ms": 42,
        },
    )
    print("✅ Tool completed recorded")

    # Test 4: Bulk write (performance test)
    print("📊 Testing bulk write performance...")
    start = time.time()

    for i in range(1000):
        await writer.record_observation(
            session_id=f"perf-session-{i % 10}",
            observation_type="token_usage",
            data={"input_tokens": i, "output_tokens": i * 2},
        )

    elapsed = time.time() - start
    print(f"✅ 1000 observations in {elapsed:.2f}s ({1000 / elapsed:.0f} obs/sec)")

    # Test 5: Query back to verify
    async with writer.pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM agent_observations WHERE session_id = $1", "test-session-1"
        )
        print(f"✅ Query verification: {count} observations for test-session-1")

        # Verify data integrity
        token_row = await conn.fetchrow(
            """
            SELECT data FROM agent_observations
            WHERE session_id = $1 AND observation_type = $2
            ORDER BY time DESC LIMIT 1
        """,
            "test-session-1",
            "token_usage",
        )

        import json

        data = (
            json.loads(token_row["data"])
            if isinstance(token_row["data"], str)
            else token_row["data"]
        )
        assert data["input_tokens"] == 1000, "Data integrity check failed"
        print("✅ Data integrity verified")

    await writer.close()
    print("\n🎉 Writer tests passed!")


if __name__ == "__main__":
    asyncio.run(test_writer())
