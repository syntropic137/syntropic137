import { clsx } from 'clsx'
import {
  Activity,
  FileText,
  GitBranch,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'

import { getMetrics, listWorkflows } from '../api/client'
import { Card, CardContent, CardHeader, EventFeed, MetricCard, PageLoader } from '../components'
import type { MetricsResponse, WorkflowSummary } from '../types'

// Polling interval for dashboard refresh (10 seconds)
const POLL_INTERVAL = 10000

export function Dashboard() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [recentWorkflows, setRecentWorkflows] = useState<WorkflowSummary[]>([])
  const [loading, setLoading] = useState(true)
  // Connection status (for live updates indicator)
  const isConnected = !loading // Consider connected once initial data is loaded

  // Refresh metrics
  const refreshMetrics = useCallback(() => {
    getMetrics()
      .then((metricsData) => setMetrics(metricsData))
      .catch(console.error)
  }, [])

  // Initial data fetch
  useEffect(() => {
    Promise.all([
      getMetrics(),
      listWorkflows({ page_size: 5, order_by: '-runs_count' }),
    ])
      .then(([metricsData, workflowsData]) => {
        setMetrics(metricsData)
        setRecentWorkflows(workflowsData.workflows)
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  // Polling for live updates (replaces SSE)
  useEffect(() => {
    const interval = setInterval(refreshMetrics, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [refreshMetrics])

  if (loading) return <PageLoader />

  // Prepare chart data
  const tokenDistribution = metrics
    ? [
      { name: 'Input', value: metrics.total_input_tokens, fill: '#6366f1' },
      { name: 'Output', value: metrics.total_output_tokens, fill: '#818cf8' },
    ]
    : []

  const workflowStatusData = metrics
    ? [
      { name: 'Completed', value: metrics.completed_workflows, fill: '#22c55e' },
      { name: 'Failed', value: metrics.failed_workflows, fill: '#ef4444' },
      { name: 'Other', value: metrics.total_workflows - metrics.completed_workflows - metrics.failed_workflows, fill: '#6366f1' },
    ].filter(d => d.value > 0)
    : []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Dashboard</h1>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            Monitor your agentic workflows in real-time
          </p>
        </div>
        {/* Connection status indicator */}
        <div className="flex items-center gap-2 text-sm">
          <span
            className={clsx(
              'h-2 w-2 rounded-full',
              isConnected ? 'bg-emerald-500' : 'bg-slate-400'
            )}
          />
          <span className="text-[var(--color-text-muted)]">
            {isConnected ? 'Live' : 'Connecting...'}
          </span>
        </div>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Total Workflows"
          value={metrics?.total_workflows ?? 0}
          icon={GitBranch}
          color="accent"
          subtitle={`${metrics?.completed_workflows ?? 0} completed`}
        />
        <MetricCard
          title="Total Sessions"
          value={metrics?.total_sessions ?? 0}
          icon={Activity}
          color="success"
        />
        <MetricCard
          title="Total Tokens"
          value={metrics?.total_tokens.toLocaleString() ?? 0}
          icon={Zap}
          subtitle={`$${Number(metrics?.total_cost_usd ?? 0).toFixed(4)}`}
        />
        <MetricCard
          title="Artifacts"
          value={metrics?.total_artifacts ?? 0}
          icon={FileText}
          subtitle={`${((metrics?.total_artifact_bytes ?? 0) / 1024).toFixed(1)} KB`}
          href="/artifacts"
        />
      </div>

      {/* Charts and event feed */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Token distribution */}
        <Card>
          <CardHeader title="Token Distribution" subtitle="Input vs Output tokens" />
          <CardContent className="h-[200px]">
            {tokenDistribution.some(d => d.value > 0) ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={tokenDistribution}
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={70}
                    paddingAngle={2}
                    dataKey="value"
                    stroke="none"
                  >
                    {tokenDistribution.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.fill} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--color-surface-elevated)',
                      border: '1px solid var(--color-border)',
                      borderRadius: '8px',
                      fontSize: '12px',
                    }}
                    formatter={(value: number) => [value.toLocaleString(), 'tokens']}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-[var(--color-text-muted)]">
                No token data yet
              </div>
            )}
            <div className="flex justify-center gap-6 -mt-4">
              {tokenDistribution.map((item) => (
                <div key={item.name} className="flex items-center gap-2">
                  <div
                    className="h-3 w-3 rounded-full"
                    style={{ backgroundColor: item.fill }}
                  />
                  <span className="text-xs text-[var(--color-text-secondary)]">{item.name}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Workflow status */}
        <Card>
          <CardHeader title="Workflow Status" subtitle="Execution outcomes" />
          <CardContent className="h-[200px]">
            {workflowStatusData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={workflowStatusData}
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={70}
                    paddingAngle={2}
                    dataKey="value"
                    stroke="none"
                  >
                    {workflowStatusData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.fill} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'var(--color-surface-elevated)',
                      border: '1px solid var(--color-border)',
                      borderRadius: '8px',
                      fontSize: '12px',
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-[var(--color-text-muted)]">
                No workflow data yet
              </div>
            )}
            <div className="flex justify-center gap-6 -mt-4">
              {workflowStatusData.map((item) => (
                <div key={item.name} className="flex items-center gap-2">
                  <div
                    className="h-3 w-3 rounded-full"
                    style={{ backgroundColor: item.fill }}
                  />
                  <span className="text-xs text-[var(--color-text-secondary)]">{item.name}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Live event feed */}
        <Card className="h-[280px]">
          <EventFeed />
        </Card>
      </div>

      {/* Recent workflows */}
      <Card>
        <CardHeader
          title="Recent Workflows"
          subtitle="Latest workflow executions"
          action={
            <a
              href="/workflows"
              className="text-xs text-[var(--color-accent)] hover:underline"
            >
              View all →
            </a>
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
              {recentWorkflows.length === 0 ? (
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
                recentWorkflows.map((workflow) => (
                  <tr
                    key={workflow.id}
                    className="border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-surface-elevated)] cursor-pointer transition-colors"
                    onClick={() => (window.location.href = `/workflows/${workflow.id}`)}
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
    </div>
  )
}
