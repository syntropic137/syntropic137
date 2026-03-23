import { Link, useNavigate } from 'react-router-dom'

import { Card, CardContent, CardHeader } from '../../components'
import type { WorkflowSummary } from '../../types'

interface RecentWorkflowsTableProps {
  workflows: WorkflowSummary[]
}

export function RecentWorkflowsTable({ workflows }: RecentWorkflowsTableProps) {
  const navigate = useNavigate()

  return (
    <Card>
      <CardHeader
        title="Recent Workflows"
        subtitle="Latest workflow executions"
        action={
          <Link
            to="/workflows"
            className="text-xs text-[var(--color-accent)] hover:underline"
          >
            View all →
          </Link>
        }
      />
      <CardContent noPadding>
        <table className="w-full">
          <thead>
            <tr className="border-b border-[var(--color-border)] text-left text-xs font-medium uppercase tracking-wider text-[var(--color-text-muted)]">
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Phases</th>
              <th className="px-4 py-3">Runs</th>
            </tr>
          </thead>
          <tbody>
            {workflows.length === 0 ? (
              <tr>
                <td
                  colSpan={4}
                  className="px-4 py-8 text-center text-sm text-[var(--color-text-muted)]"
                >
                  No workflows yet. Run your first workflow with{' '}
                  <code className="rounded bg-[var(--color-surface-elevated)] px-1.5 py-0.5 text-xs">
                    syn run workflow.yaml
                  </code>
                </td>
              </tr>
            ) : (
              workflows.map((workflow) => (
                <tr
                  key={workflow.id}
                  className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-surface-elevated)] cursor-pointer transition-colors"
                  onClick={() => navigate(`/workflows/${workflow.id}`)}
                >
                  <td className="px-4 py-3">
                    <span className="text-sm font-medium text-[var(--color-text-primary)]">
                      {workflow.name}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-[var(--color-text-secondary)]">
                      {workflow.workflow_type}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-[var(--color-text-secondary)]">
                      {workflow.phase_count}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-[var(--color-text-secondary)]">
                      {workflow.runs_count}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}
