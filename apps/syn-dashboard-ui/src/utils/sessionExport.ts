/**
 * Session export formatters for the multi-select action bar.
 *
 * `formatSessionIds` produces a space-separated list ready for shell pipes.
 * `formatSessionsForClaude` produces a markdown block (header + table + CLI
 * snippets) that renders cleanly when pasted into a Claude conversation,
 * giving the agent both context and next-step affordance.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import type { SessionSummary } from '../types'

/** Space-separated session IDs (shell-friendly). */
export function formatSessionIds(ids: string[]): string {
  return ids.join(' ')
}

function dash(value: string | null | undefined): string {
  return value && value.length > 0 ? value : '-'
}

function escapeCell(value: string): string {
  return value.replace(/\|/g, '\\|').replace(/\n/g, ' ')
}

function rowFor(s: SessionSummary): string {
  const cells = [
    s.id,
    dash(s.workflow_name ?? s.workflow_id),
    dash(s.phase_id),
    s.status,
    s.total_tokens_display ?? String(s.total_tokens ?? 0),
    s.total_cost_display ?? '-',
    s.duration_display ?? '-',
    dash(s.started_at),
  ]
  return `| ${cells.map((c) => escapeCell(c)).join(' | ')} |`
}

/**
 * Build a markdown block describing the selected sessions:
 *   - heading with count
 *   - table of key fields per session
 *   - fenced code block of `syn session show <id>` snippets
 *
 * Returns an empty string when no sessions are selected.
 */
export function formatSessionsForClaude(sessions: SessionSummary[]): string {
  if (sessions.length === 0) return ''

  const heading = `## Selected sessions (${sessions.length})`
  const tableHeader = '| Session ID | Workflow | Phase | Status | Tokens | Cost | Duration | Started |'
  const tableSep = '| --- | --- | --- | --- | --- | --- | --- | --- |'
  const tableRows = sessions.map(rowFor)
  const cli = ['```bash', ...sessions.map((s) => `syn session show ${s.id}`), '```']

  return [heading, '', tableHeader, tableSep, ...tableRows, '', ...cli].join('\n')
}
