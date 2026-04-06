import { BarChart3 } from 'lucide-react'

import { EmptyState } from '../components'

export function Insights() {
  return (
    <div>
      <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Insights</h1>
      <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
        Global system insights, cost analysis, and contribution heatmaps.
      </p>
      <div className="mt-8">
        <EmptyState
          icon={BarChart3}
          title="Coming Soon"
          description="Insights dashboards are under active development. Use the CLI for now: syn insights overview, syn insights cost, syn insights heatmap."
        />
      </div>
    </div>
  )
}
