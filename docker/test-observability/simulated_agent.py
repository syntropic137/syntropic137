#!/usr/bin/env python3
"""
Simulated agent execution for E2E testing.
This simulates a realistic agent workflow without requiring the full AEF stack.
"""
import asyncio
from observability_writer import ObservabilityWriter


class SimulatedAgent:
    """Simulate agent execution with realistic observation patterns."""

    def __init__(self, writer: ObservabilityWriter):
        self.writer = writer

    async def run_task(self, session_id: str, execution_id: str, task: str):
        """Simulate agent execution with observations."""
        print(f"🤖 Agent starting task: {task}")
        print(f"   Session: {session_id}")
        print(f"   Execution: {execution_id}")

        # Simulate 3 turns of agent interaction
        for turn in range(3):
            print(f"\n  📝 Turn {turn + 1}...")

            # Token usage per turn (realistic patterns)
            if turn == 0:
                # First turn: Large context, cache creation
                input_tokens = 15000
                output_tokens = 2000
                cache_creation = 8000
                cache_read = 0
            elif turn == 1:
                # Second turn: Cache hit, reduced input
                input_tokens = 5000
                output_tokens = 3000
                cache_creation = 0
                cache_read = 12000
            else:
                # Final turn: Smaller context
                input_tokens = 3000
                output_tokens = 1500
                cache_creation = 0
                cache_read = 10000

            await self.writer.record_observation(
                session_id=session_id,
                observation_type='token_usage',
                execution_id=execution_id,
                data={
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens,
                    'cache_creation_tokens': cache_creation,
                    'cache_read_tokens': cache_read
                }
            )
            print(f"    ✓ Token usage: {input_tokens:,} in, {output_tokens:,} out")

            # Tool calls per turn (2 tools per turn)
            for tool_idx in range(2):
                tool_use_id = f'toolu_{turn}_{tool_idx}'
                tool_name = 'bash' if tool_idx == 0 else 'Read'

                # Tool started
                await self.writer.record_observation(
                    session_id=session_id,
                    observation_type='tool_started',
                    execution_id=execution_id,
                    data={
                        'tool_name': tool_name,
                        'tool_use_id': tool_use_id,
                        'input': {
                            'command': f'echo "Turn {turn}"' if tool_name == 'bash' else None,
                            'path': f'file_{turn}.py' if tool_name == 'Read' else None
                        }
                    }
                )

                # Simulate tool execution time
                await asyncio.sleep(0.05)

                # Tool completed
                await self.writer.record_observation(
                    session_id=session_id,
                    observation_type='tool_completed',
                    execution_id=execution_id,
                    data={
                        'tool_name': tool_name,
                        'tool_use_id': tool_use_id,
                        'output': f'Result from {tool_name} in turn {turn}',
                        'duration_ms': 50 + tool_idx * 10
                    }
                )
                print(f"    ✓ Tool: {tool_name}")

        print("\n✅ Agent task complete")
