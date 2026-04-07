import { clsx } from 'clsx'
import {
  Activity,
  FileText,
  GitBranch,
  Zap,
} from 'lucide-react'

import { Card, CardContent, CardHeader, EventFeed, MetricCard, PageLoader } from '../../components'
import { useDashboardData } from '../../hooks/useDashboardData'
import { ContributionHeatmap } from './ContributionHeatmap'
import { DashboardCharts, WorkflowStatusChart } from './DashboardCharts'
import { RecentWorkflowsTable } from './RecentWorkflowsTable'

export function Dashboard() {
  const { metrics, recentWorkflows, loading, isConnected } = useDashboardData()

  if (loading) return <PageLoader />

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

      {/* Contribution heatmap */}
      <ContributionHeatmap />

      {/* Charts and event feed */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader title="Token Distribution" subtitle="Input vs Output tokens" />
          <CardContent className="h-[200px]">
            <DashboardCharts metrics={metrics} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader title="Workflow Status" subtitle="Execution outcomes" />
          <CardContent className="h-[200px]">
            <WorkflowStatusChart metrics={metrics} />
          </CardContent>
        </Card>

        <Card className="h-[280px]">
          <EventFeed />
        </Card>
      </div>

      {/* Recent workflows */}
      <RecentWorkflowsTable workflows={recentWorkflows} />
    </div>
  )
}
