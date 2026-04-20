import { describe, expect, it } from 'vitest'
import type { SessionSummary } from '../../types'
import { formatSessionIds, formatSessionsForClaude } from '../sessionExport'

const sample = (overrides: Partial<SessionSummary> = {}): SessionSummary =>
  ({
    id: 'sess_abc123',
    workflow_id: 'wf-1',
    workflow_name: 'Deploy Pipeline',
    execution_id: 'exec-1',
    phase_id: 'build',
    status: 'completed',
    agent_provider: null,
    agent_model: null,
    agent_model_display: null,
    total_tokens: 1234,
    total_tokens_display: '1.2k',
    total_cost_usd: 0.045,
    total_cost_display: '$0.045',
    duration_seconds: 12,
    duration_display: '12s',
    started_at: '2026-04-19T10:00:00Z',
    completed_at: '2026-04-19T10:00:12Z',
    ...overrides,
  }) as SessionSummary

describe('formatSessionIds', () => {
  it('returns empty string for empty list', () => {
    expect(formatSessionIds([])).toBe('')
  })

  it('returns single id unchanged', () => {
    expect(formatSessionIds(['sess_a'])).toBe('sess_a')
  })

  it('joins multiple ids with spaces', () => {
    expect(formatSessionIds(['sess_a', 'sess_b', 'sess_c'])).toBe('sess_a sess_b sess_c')
  })
})

describe('formatSessionsForClaude', () => {
  it('returns empty string for no sessions', () => {
    expect(formatSessionsForClaude([])).toBe('')
  })

  it('includes heading with count', () => {
    const out = formatSessionsForClaude([sample(), sample({ id: 'sess_b' })])
    expect(out.startsWith('## Selected sessions (2)')).toBe(true)
  })

  it('emits a markdown table with all key columns', () => {
    const out = formatSessionsForClaude([sample()])
    expect(out).toContain('| Session ID | Workflow | Phase | Status | Tokens | Cost | Duration | Started |')
    expect(out).toContain('| sess_abc123 | Deploy Pipeline | build | completed | 1.2k | $0.045 | 12s | 2026-04-19T10:00:00Z |')
  })

  it('emits a fenced code block of syn session show snippets', () => {
    const out = formatSessionsForClaude([sample({ id: 'sess_a' }), sample({ id: 'sess_b' })])
    expect(out).toContain('```bash')
    expect(out).toContain('syn session show sess_a')
    expect(out).toContain('syn session show sess_b')
    expect(out.endsWith('```')).toBe(true)
  })

  it('renders a dash for missing optional fields', () => {
    const out = formatSessionsForClaude([
      sample({ workflow_name: null, workflow_id: null, phase_id: null, started_at: null }),
    ])
    expect(out).toContain('| sess_abc123 | - | - | completed |')
    expect(out).toContain('| - |\n')
  })

  it('escapes pipes in cell values', () => {
    const out = formatSessionsForClaude([sample({ workflow_name: 'a|b' })])
    expect(out).toContain('a\\|b')
  })

  it('falls back to total_tokens when display string is missing', () => {
    const out = formatSessionsForClaude([sample({ total_tokens_display: undefined as unknown as string, total_tokens: 99 })])
    expect(out).toContain('| 99 |')
  })
})
