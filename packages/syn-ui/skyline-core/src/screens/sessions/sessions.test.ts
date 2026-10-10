import { describe, expect, it } from 'vitest'
import { UNKNOWN } from '../../format/shared'
import {
  agentLabel,
  sessionDurationText,
  commitUrl,
  costByModelRows,
  filterOperations,
  operationChips,
  operationsSummary,
  revealCount,
  sessionCost,
  sessionCrumbs,
  sessionOperations,
  sessionListRow,
  sessionsLede,
  sessionsLedeShort,
  summarizeToolInput,
  transcriptAvailable,
  windowRange,
  type SessionOperationInput,
} from './index'

const T = (s: number) => new Date(Date.UTC(2026, 9, 8, 13, 32, s)).toISOString()
const tz = { timeZone: 'UTC' }

const events: SessionOperationInput[] = [
  { operation_id: 'a1', operation_type: 'tool_execution_started', timestamp: T(22), success: true, tool_name: 'Bash', tool_use_id: 'u1', tool_input: { command: 'ls -la' } },
  { operation_id: 'a2', operation_type: 'tool_execution_completed', timestamp: T(23), success: true, tool_name: 'Bash', tool_use_id: 'u1', tool_output: 'total 8', duration_seconds: 1.2 },
  { operation_id: 'b1', operation_type: 'tool_execution', timestamp: T(36), success: false, tool_name: 'Bash', tool_use_id: 'u2', tool_input: { command: 'python -m py_compile x.py' }, tool_output: 'python: command not found' },
  { operation_id: 'c1', operation_type: 'tool_execution', timestamp: T(31), success: true, tool_name: 'Edit', tool_use_id: 'u3', tool_input: { file_path: '/workspace/palindrome.py' } },
  { operation_id: 'd1', operation_type: 'token_usage', timestamp: T(32), success: true },
  { operation_id: 'e1', operation_type: 'message_request', timestamp: T(20), success: true, message_role: 'user', message_content: 'Run the phase.\nDetails' },
  { operation_id: 'f1', operation_type: 'git_commit', timestamp: T(50), success: true, git_sha: 'abcdef1234', git_branch: 'main', git_repo: 'syntropic137/syntropic137', git_message: 'feat: x' },
  {
    operation_id: 'g1',
    operation_type: 'tool_execution',
    timestamp: T(46),
    success: true,
    tool_name: 'Bash',
    tool_use_id: 'u4',
    duration_seconds: 6,
    tool_input: { command: 'claude -p --output-format stream-json "Review"' },
    tool_output: '{"type":"system","session_id":"35468ba1-dca4-4f8c-9012-4fb500342e79"}',
  },
]

describe('sessionOperations', () => {
  const rows = sessionOperations(events, tz)

  it('merges start and finish, sorts oldest first and drops bookkeeping', () => {
    expect(rows.map((r) => r.id)).toEqual(['e1', 'a1', 'c1', 'b1', 'g1', 'f1'])
    const ls = rows[1]!
    expect(ls).toMatchObject({ tool: 'Bash', input: 'ls -la', output: 'total 8', status: 'ok', duration: '1s' })
    expect(ls.time).toBe('1:32:22 PM')
  })

  it('marks failures, quiet rows and git rows', () => {
    expect(rows.find((r) => r.id === 'b1')!.status).toBe('failed')
    expect(rows[0]).toMatchObject({ tool: 'Prompt', input: 'Run the phase.', status: 'quiet', isTool: false })
    expect(rows.find((r) => r.id === 'f1')).toMatchObject({ kind: 'git', tool: 'Commit', input: 'abcdef1 · main · syntropic137/syntropic137', commitUrl: 'https://github.com/syntropic137/syntropic137/commit/abcdef1234' })
  })

  it('detects a hand-off to another agent', () => {
    expect(rows.find((r) => r.id === 'g1')!.delegated).toMatchObject({ agentKind: 'claude', id: '35468ba1', href: '/sessions/35468ba1-dca4-4f8c-9012-4fb500342e79' })
  })

  it('keeps an unfinished start as running', () => {
    const r = sessionOperations([events[0]!], tz)
    expect(r[0]!.status).toBe('running')
  })
})

describe('chips, filter and summary', () => {
  const rows = sessionOperations(events, tz)
  it('lists tools by frequency then errors', () => {
    expect(operationChips(rows)).toEqual([
      { value: 'all', label: 'All', count: 6 },
      { value: 'bash', label: 'Bash', count: 3 },
      { value: 'edit', label: 'Edit', count: 1 },
      { value: 'errors', label: 'Errors', count: 1 },
    ])
  })
  it('filters', () => {
    expect(filterOperations(rows, 'errors').map((r) => r.id)).toEqual(['b1'])
    expect(filterOperations(rows, 'edit')).toHaveLength(1)
    expect(filterOperations(rows, 'all')).toHaveLength(6)
  })
  it('summarises', () => {
    expect(operationsSummary(rows, 6, 8, 'all')).toBe('4 tool calls from 8 recorded events, newest first')
    expect(operationsSummary(rows, 1, 8, 'errors')).toBe('1 of 6 operations shown')
  })
})

describe('helpers', () => {
  it('summarises tool input', () => {
    expect(summarizeToolInput({ command: 'ls' })).toBe('ls')
    expect(summarizeToolInput({ file_path: '/a' })).toBe('/a')
    expect(summarizeToolInput({ x: 1 })).toBe('{"x":1}')
    expect(summarizeToolInput(null)).toBe('')
    expect(summarizeToolInput({ skill: 'documentation', args: 'x' })).toBe('documentation')
  })
  it('reads the path out of a raw (unparsed, possibly truncated) tool input', () => {
    expect(summarizeToolInput({ raw: '{"file_path": "/w/out.md", "content": "ok"}' })).toBe('/w/out.md')
    expect(summarizeToolInput({ raw: '{"file_path": "/w/pr \\"body\\".md", "content": "Closes #1. cut sh' })).toBe('/w/pr "body".md')
    expect(summarizeToolInput({ raw: 'not json' })).toBe('{"raw":"not json"}')
  })
  it('builds commit urls only for GitHub repos', () => {
    expect(commitUrl('https://github.com/a/b.git', 'f00')).toBe('https://github.com/a/b/commit/f00')
    expect(commitUrl('nope', 'f00')).toBeUndefined()
    expect(commitUrl('a/b', null)).toBeUndefined()
  })
  it('orders cost rows and picks the agent tone', () => {
    expect(costByModelRows({ small: '0.01', big: '0.2' }, 'codex')).toEqual([
      { label: 'big', value: 0.2, tone: 'codex' },
      { label: 'small', value: 0.01, tone: 'codex' },
    ])
    expect(costByModelRows(null)).toEqual([])
  })
  it('flags incomplete cost', () => {
    expect(sessionCost(0.2162, 0)).toEqual({ display: '$0.2162' })
    expect(sessionCost(0.2162, 2).display).toBe('$0.2162+')
  })
  it('labels the agent', () => {
    expect(agentLabel('codex', 'gpt-5.6-sol')).toBe('Codex · gpt-5.6-sol')
    expect(agentLabel(null, null)).toBe('—')
    // Feedback 58868cd8: never "unknown", never the requested alias; harness plus "model not reported".
    expect(agentLabel('codex', 'unknown', null)).toBe('Codex · model not reported')
    expect(agentLabel('codex', 'unknown (requested: gpt-sol)', null)).toBe('Codex · model not reported')
    expect(agentLabel('codex', 'unknown (requested: gpt-sol)')).toBe('Codex · model not reported')
    expect(agentLabel('claude', 'claude-opus-5-5', 'claude-opus-5-5')).toBe('Claude · claude-opus-5-5')
    expect(agentLabel(null, 'unknown', null)).toBe('—')
  })
  it('builds crumbs', () => {
    expect(sessionCrumbs({ id: 'sess-1', workflow_id: 'wf', workflow_name: 'Codex delegates to Claude', execution_id: 'exec-6350e65e', phase_display: 'build-and-delegate' })).toEqual([
      { label: 'Workflows', href: '/workflows' },
      { label: 'Codex delegates to Claude', href: '/workflows/wf' },
      { label: 'Execution', id: '6350e65e', href: '/executions/exec-6350e65e' },
      { label: 'build-and-delegate' },
    ])
    expect(sessionCrumbs({ id: 'abcdef123456' })).toEqual([{ label: 'Sessions', href: '/sessions' }, { label: 'Session', id: 'abcdef12' }])
  })
  it('knows when the transcript exists', () => {
    expect(transcriptAvailable('running')).toBe(false)
    expect(transcriptAvailable('failed')).toBe(true)
  })
})

describe('windowRange', () => {
  it('renders only the rows near the viewport', () => {
    expect(windowRange({ offset: 0, viewport: 600, rowHeight: 60, count: 1000, overscan: 2 })).toEqual({ start: 0, end: 13, padTop: 0, padBottom: 987 * 60 })
    const r = windowRange({ offset: 6000, viewport: 600, rowHeight: 60, count: 1000, overscan: 2 })
    expect(r.start).toBe(98)
    expect(r.end).toBe(113)
    expect(r.padTop + (r.end - r.start) * 60 + r.padBottom).toBe(60_000)
  })
  it('clamps at the end and handles empty lists', () => {
    const r = windowRange({ offset: 99_999, viewport: 600, rowHeight: 60, count: 10 })
    expect(r.end).toBe(10)
    expect(r.start).toBeLessThan(10)
    expect(windowRange({ offset: 0, viewport: 600, rowHeight: 60, count: 0 })).toEqual({ start: 0, end: 0, padTop: 0, padBottom: 0 })
  })
  it('reveals in chunks', () => {
    expect(revealCount(40, 100)).toBe(80)
    expect(revealCount(80, 100)).toBe(100)
  })
})

describe('list rows', () => {
  const row = { id: 's1', workflow_name: 'Codex delegates to Claude', phase_display: 'Delegate', agent_provider: 'codex', agent_model_display: 'gpt-5.6-sol', repos_display: 'a/b', status: 'completed', total_tokens_display: '176.0K', total_cost_display: '$0.2162', duration_display: '57s' }
  it('builds the sub line', async () => {
    const { sessionRowSub } = await import('./index')
    expect(sessionRowSub(row)).toBe('Delegate · Codex · gpt-5.6-sol · a/b')
    expect(sessionRowSub({ id: 'x', status: 'running' })).toBe('')
  })
  it('formats sessions for an agent', async () => {
    const { sessionsForAgent } = await import('./index')
    expect(sessionsForAgent([row])).toBe('- session s1: Codex delegates to Claude / Delegate · completed · 176.0K tokens · $0.2162 · 57s')
  })

  it('writes the Sessions hero ledes', () => {
    expect(sessionsLede({ total: 118, running: 0 })).toBe('One agent run per phase, plus any child sessions it hands off to. 118 so far, none running.')
    expect(sessionsLede({ total: 0, running: 0 })).toMatch(/None yet\.$/)
    expect(sessionsLedeShort({ total: 1, running: 2 })).toBe('1 agent run, 2 running now')
  })
  it('leads a list row with the phase and marks delegated children', () => {
    const base = { id: 'a41c09e7-1111', status: 'failed', workflow_name: 'PR Review', phase_display: 'review', execution_id: 'exec-e93b07d2aaaa', agent_provider: 'claude', agent_model: 'claude-sonnet-5-5', agent_model_display: 'claude-sonnet-5-5', repos_display: 'syntropic137' }
    expect(sessionListRow(base)).toEqual({ title: 'review', delegated: false, sub: 'a41c09e7 · syntropic137', workflow: 'PR Review', execution: 'exec e93b07d2', agent: 'Claude · claude-sonnet-5-5', provider: 'Claude', model: 'claude-sonnet-5-5' })
    const child = sessionListRow({ ...base, id: '35468ba1-x', parent_session_id: '2fd5ec12-y', agent_model: null, agent_model_display: 'gpt-sol (requested)' })
    expect(child.title).toBe('review (delegated)')
    expect(child.sub).toBe('35468ba1 · child of 2fd5ec12')
    expect(child.agent).toBe('Claude · model not reported')
    expect(child.model).toBe('model not reported')
  })
})

describe('session duration (parity-2 #6: detail said "2m", API and list say "1m 59s")', () => {
  it("renders the API's duration_display verbatim", () => {
    expect(sessionDurationText({ duration_seconds: 119.799, duration_display: '1m 59s' })).toBe('1m 59s')
  })
  it('falls back to the precise format only when the server sent no display', () => {
    expect(sessionDurationText({ duration_seconds: 24.3 })).toBe('24.3s')
    expect(sessionDurationText({ duration_seconds: 7 })).toBe('7s')
    expect(sessionDurationText({ duration_seconds: null })).toBe(UNKNOWN)
  })
})
