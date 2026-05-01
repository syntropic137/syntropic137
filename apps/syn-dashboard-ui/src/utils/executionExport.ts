/**
 * Execution export formatters for the multi-select action bar.
 *
 * Mirrors sessionExport: a space-separated id list for shells, plus a
 * markdown block (header + table + CLI snippets) for pasting into any
 * agent conversation.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import type { ExecutionListItem } from '../types'

/** Space-separated execution IDs (shell-friendly). */
export function formatExecutionIds(ids: string[]): string {
  return ids.join(' ')
}

function dash(value: string | null | undefined): string {
  return value && value.length > 0 ? value : '-'
}

function escapeCell(value: string): string {
  return value.replace(/\|/g, '\\|').replace(/\n/g, ' ')
}

function rowFor(e: ExecutionListItem): string {
  const cells = [
    e.workflow_execution_id,
    dash(e.workflow_name || e.workflow_id),
    e.status,
    `${e.completed_phases}/${e.total_phases}`,
    e.total_tokens_display ?? String(e.total_tokens ?? 0),
    e.total_cost_display ?? '-',
    e.duration_display ?? '-',
    dash(e.started_at),
  ]
  return `| ${cells.map((c) => escapeCell(c)).join(' | ')} |`
}

/**
 * Build a markdown block describing the selected executions:
 *   - heading with count
 *   - table of key fields per execution
 *   - fenced code block of `syn execution show <id>` snippets
 *
 * Returns an empty string when no executions are selected.
 */
export function formatExecutionsForAgent(executions: ExecutionListItem[]): string {
  if (executions.length === 0) return ''

  const heading = `## Selected executions (${executions.length})`
  const tableHeader =
    '| Execution ID | Workflow | Status | Progress | Tokens | Cost | Duration | Started |'
  const tableSep = '| --- | --- | --- | --- | --- | --- | --- | --- |'
  const tableRows = executions.map(rowFor)
  const cli = [
    '```bash',
    ...executions.map((e) => `syn execution show ${e.workflow_execution_id}`),
    '```',
  ]

  return [heading, '', tableHeader, tableSep, ...tableRows, '', ...cli].join('\n')
}
