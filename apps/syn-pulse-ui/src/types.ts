export interface HeatmapDayBucket {
  date: string
  count: number
  breakdown: {
    sessions: number
    executions: number
    commits: number
    cost_usd: number
    tokens: number
    input_tokens: number
    output_tokens: number
    cache_creation_tokens: number
    cache_read_tokens: number
  }
}

export interface ContributionHeatmapResult {
  metric: string
  start_date: string
  end_date: string
  total: number
  days: HeatmapDayBucket[]
  filter: {
    organization_id: string | null
    system_id: string | null
    repo_id: string | null
  }
}

export type MetricKey = 'sessions' | 'executions' | 'commits' | 'cost_usd' | 'tokens'

export interface OrgSummary {
  organization_id: string
  name: string
}

export interface SystemSummary {
  system_id: string
  organization_id: string
  name: string
}

export interface RepoSummary {
  repo_id: string
  full_name: string
  system_id: string
  organization_id: string
}
