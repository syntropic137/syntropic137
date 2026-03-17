import { useCallback, useEffect, useState } from 'react'
import { Activity } from 'lucide-react'

import { getContributionHeatmap } from '../api/client'
import { ContributionHeatmap } from '../components/ContributionHeatmap'
import { FilterBar } from '../components/FilterBar'
import { GlassPanel } from '../components/GlassPanel'
import type { ContributionHeatmapResult } from '../types'

export function PulseDashboard() {
  const [filter, setFilter] = useState<{
    organization_id?: string
    system_id?: string
    repo_id?: string
  }>({})
  const [data, setData] = useState<ContributionHeatmapResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [fetchKey, setFetchKey] = useState(0)

  // Reset loading state synchronously when filter changes
  const handleFilterChange = useCallback((f: typeof filter) => {
    setFilter(f)
    setLoading(true)
    setFetchKey((k) => k + 1)
  }, [])

  useEffect(() => {
    let cancelled = false
    getContributionHeatmap({ ...filter, metric: 'sessions' })
      .then((result) => {
        if (!cancelled) {
          setData(result)
          setError(null)
          setLoading(false)
        }
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setError(e.message)
          setLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [filter, fetchKey])

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Activity size={28} style={{ color: 'var(--color-accent-primary)' }} />
        <div>
          <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            Syntropic137 Pulse
          </h1>
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            Agent contribution activity
          </p>
        </div>
      </div>

      {/* Filters */}
      <GlassPanel>
        <FilterBar onFilterChange={handleFilterChange} />
      </GlassPanel>

      {/* Heatmap */}
      <GlassPanel>
        {loading && (
          <div className="flex items-center justify-center py-12" style={{ color: 'var(--color-text-muted)' }}>
            Loading heatmap data...
          </div>
        )}
        {error && (
          <div className="flex items-center justify-center py-12" style={{ color: 'var(--color-error)' }}>
            {error}
          </div>
        )}
        {data && !loading && !error && (
          <ContributionHeatmap
            days={data.days}
            startDate={data.start_date}
            endDate={data.end_date}
          />
        )}
      </GlassPanel>
    </div>
  )
}
