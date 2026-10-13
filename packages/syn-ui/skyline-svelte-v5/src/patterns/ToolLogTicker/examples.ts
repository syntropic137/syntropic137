/** Example rows of the Tool Log Ticker for /dev/patterns: the Landing board's run #142 (sample data). */
import type { ToolLogRow } from '@syn137/skyline-core/patterns'

export const TOOL_LOG_EXAMPLE_ROWS: readonly ToolLogRow[] = [
  { time: '14:02:11', tool: 'Read', target: 'src/domain/aggregate.py', duration: '42ms' },
  { time: '14:02:14', tool: 'Grep', target: '"apply_event" -n', duration: '118ms' },
  { time: '14:02:19', tool: 'Bash', target: 'pytest -q tests/domain', duration: '8.4s' },
  { time: '14:02:31', tool: 'Write', target: 'docs/event-sourcing.md', duration: '12ms' },
  { time: '14:02:33', tool: 'Read', target: 'src/projections/list.py', duration: '31ms' },
  { time: '14:02:40', tool: 'Edit', target: 'projection.py +12 −3', duration: '9ms' },
  { time: '14:02:52', tool: 'Bash', target: 'ruff check .', duration: '1.2s' },
  { time: '14:03:01', tool: 'Read', target: 'tests/test_replay.py', duration: '28ms' },
]
