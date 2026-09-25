import { clsx } from 'clsx'
import { AlertTriangle, CheckCircle2, DollarSign, FileText, Play, ShieldAlert, XCircle } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  Breadcrumbs,
  Card,
  EmptyState,
  MetricCard,
  ModelBreakdown,
  PageLoader,
  StatusBadge,
} from '../../components'
import { TokenBreakdown } from '../../components/TokenBreakdown'
import type { BreadcrumbItem } from '../../components/Breadcrumbs'
import { ExecutionControl } from '../../components/ExecutionControl'
import { useExecutionData } from '../../hooks'
import type { ExecutionDetailResponse, FailureClassification, ReportedFailureReason } from '../../types'
import { type ExactUsd, exactUsdToString, parseExactUsd } from '../../utils/exactUsd'
import { executionTokenTotals } from '../../utils/executionTokens'
import { isPlatformFailure, reportedFailureNote } from '../../utils/executionOutcome'
import { formatCostWithCoverage, formatDurationFromRange } from '../../utils/formatters'
import { ArtifactSection } from './ArtifactSection'
import { PhaseTimeline } from './PhaseTimeline'

type Phase = ExecutionDetailResponse['phases'][number]

function ReposPanel({ repos }: { repos: string[] }) {
  if (repos.length === 0) return null
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <h3 className="mb-2 text-sm font-medium text-[var(--color-text-muted)]">Repositories</h3>
      <ul className="space-y-1">
        {repos.map((url) => {
          const name = url.split('/').pop()?.replace(/\.git$/, '') ?? url
          return (
            <li key={url} className="text-sm">
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--color-accent)] hover:underline"
                title={url}
              >
                {name}
              </a>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/**
 * Per-model costs summed across the phases.
 *
 * This is the only per-model source there is: `ExecutionDetailResponse` has no
 * execution-level `cost_by_model`, and the domain leaves a running phase's map
 * empty, so mid-run this accounts for less than `total_cost_usd` -- often for
 * nothing at all. The card is given the execution's own total alongside it and
 * reconciles the two; do not treat this sum as the execution's cost.
 */
function aggregateCostByModel(phases: Phase[]): Record<string, string> {
  // Summed exactly: the card downstream reconciles this against the
  // execution's decimal total, and float sums are what made that disagree.
  const totals = new Map<string, ExactUsd>()
  for (const phase of phases) {
    for (const [model, costStr] of Object.entries(phase.cost_by_model ?? {})) {
      const cost = parseExactUsd(costStr)
      if (cost === null) continue
      totals.set(model, (totals.get(model) ?? 0n) + cost)
    }
  }
  return Object.fromEntries(Array.from(totals.entries()).map(([m, v]) => [m, exactUsdToString(v)]))
}

/**
 * Whether what you are looking at is current, in one place.
 *
 * Two things can make the page stale and they used to be reported at opposite
 * extremes: a dropped SSE connection showed a grey dot, while a single failed
 * poll replaced the entire page with "Execution not found". The page polls
 * every 3 seconds for the length of a run now, so one transient 502 in a
 * multi-hour execution was near-certain, and its effect was permanent (#1048).
 *
 * A failed refresh does not invalidate the figures already on screen; it only
 * means they stopped advancing. Say that, and keep the figures.
 */
function FreshnessIndicator({
  isConnected,
  refreshError,
}: {
  isConnected: boolean
  refreshError: string | null
}) {
  if (refreshError) {
    return (
      <div className="flex items-center gap-2 text-sm" title={refreshError}>
        <AlertTriangle className="h-4 w-4 text-amber-400" />
        <span className="text-amber-400">Not updating &mdash; showing last known values</span>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={clsx('h-2 w-2 rounded-full', isConnected ? 'bg-emerald-500' : 'bg-slate-400')} />
      <span className="text-[var(--color-text-muted)]">{isConnected ? 'Live' : 'Connecting...'}</span>
    </div>
  )
}

/**
 * Why this run ended, in the register the run deserves.
 *
 * "Execution Failed" in red is a report that the platform broke, and it was
 * shown for every non-empty `error_message` - including the ones that say a
 * phase read its own work and judged it not deliverable. That is the gate
 * doing its job, reported as an outage, directly beneath an amber `refused`
 * badge saying the opposite (#1367).
 *
 * The heading and the colour move together, because they are one claim made
 * twice: an operator who cannot separate amber from red must still be able to
 * read which of the two happened.
 *
 * AND WHAT THE AGENT SAID IS SHOWN BESIDE THEM, NOT INSTEAD OF THEM (#1392).
 * The heading, the icon and the colour are all the platform's own finding.
 * The phase's word for what caused the failure is a different kind of fact -
 * nothing corroborates it but a clean exit - so it is rendered under them as
 * a quotation, in the muted register a quotation gets, and it changes none of
 * the three. An operator who wants to know what the agent thought can read
 * it; an operator counting outages is not shown a claim the run made about
 * itself dressed as a measurement.
 */
function ExecutionErrorCard({
  message,
  status,
  failureClassification,
  reportedFailureReason,
}: {
  message: string
  status: string
  failureClassification?: FailureClassification
  reportedFailureReason?: ReportedFailureReason | null
}) {
  const broke = isPlatformFailure(status, failureClassification)
  const reported = reportedFailureNote(reportedFailureReason)
  const Icon = broke ? XCircle : ShieldAlert
  return (
    <Card>
      <div
        className={clsx(
          'flex items-start gap-3 p-4 rounded-lg border',
          broke ? 'bg-red-500/10 border-red-500/30' : 'bg-amber-500/10 border-amber-500/30',
        )}
      >
        <Icon
          className={clsx('h-5 w-5 shrink-0 mt-0.5', broke ? 'text-red-400' : 'text-amber-400')}
        />
        <div>
          <p className={clsx('text-sm font-medium', broke ? 'text-red-400' : 'text-amber-400')}>
            {broke ? 'Execution Failed' : 'Phase Reported Failure'}
          </p>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">{message}</p>
          {reported && (
            <p className="mt-2 text-xs text-[var(--color-text-muted)]">{reported}</p>
          )}
        </div>
      </div>
    </Card>
  )
}

const CONTROLLABLE_STATUSES = new Set(['running', 'paused'])

function ExecutionHeader({ execution, executionId, isConnected, refreshError, now, refreshExecution }: {
  execution: ExecutionDetailResponse
  executionId: string | undefined
  isConnected: boolean
  refreshError: string | null
  now: number
  refreshExecution: () => void
}) {
  const showControl = !!executionId && CONTROLLABLE_STATUSES.has(execution.status)
  return (
    <div className="flex justify-between items-start">
      <div>
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20">
            <Play className="h-6 w-6 text-emerald-400" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Execution</h1>
              <StatusBadge
                status={execution.status}
                failureClassification={execution.failure_classification}
                size="lg"
                pulse={execution.status === 'running'}
              />
            </div>
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">{execution.workflow_name}</p>
            <div className="mt-2 flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
              <span className="font-mono">{execution.workflow_execution_id}</span>
              <span>&bull;</span>
              <span>Duration: {formatDurationFromRange(execution.started_at, execution.completed_at, now)}</span>
            </div>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-4">
        {showControl && (
          <ExecutionControl
            executionId={executionId}
            initialState={execution.status as 'running' | 'paused'}
            onSuccess={refreshExecution}
          />
        )}
        <FreshnessIndicator isConnected={isConnected} refreshError={refreshError} />
      </div>
    </div>
  )
}

function ExecutionMetricsGrid({
  execution,
  hasCostByModel,
}: {
  execution: ExecutionDetailResponse
  hasCostByModel: boolean
}) {
  const completedPhases = execution.phases.filter((p) => p.status === 'completed').length
  // The denominator is what the run SET OUT to do, and `phases` cannot say:
  // it holds the phases that STARTED, so a three-phase run that died in phase
  // one rendered as "0/1" - a complete-looking run of one phase, with the two
  // that never ran indistinguishable from phases that do not exist (#1147).
  //
  // An em dash, not the phase tally, when the count is unknown: falling back
  // to `phases.length` is the number that was wrong, and it looks right.
  const totalPhases = execution.total_phases > 0 ? execution.total_phases : '—'
  const tokens = executionTokenTotals(execution)
  const attributedIn = tokens.inputTokens + tokens.cacheCreationTokens + tokens.cacheReadTokens
  const inOutSubtitle = `In: ${attributedIn.toLocaleString()} / Out: ${tokens.outputTokens.toLocaleString()}`

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <MetricCard
        title="Phases"
        value={`${completedPhases}/${totalPhases}`}
        icon={CheckCircle2}
        color="success"
        subtitle={`${completedPhases} completed, ${execution.artifact_ids.length} artifact${execution.artifact_ids.length !== 1 ? 's' : ''}`}
        scrollToId="phase-timeline"
      />
      <MetricCard
        title="Total Tokens"
        value={tokens.total.toLocaleString()}
        icon={FileText}
        subtitle={
          tokens.inProgressTokens > 0
            ? `${inOutSubtitle} / ${tokens.inProgressTokens.toLocaleString()} in progress`
            : inOutSubtitle
        }
        scrollToId="token-breakdown"
      />
      <MetricCard
        title="Total Cost"
        value={formatCostWithCoverage(
          Number(execution.total_cost_usd),
          execution.unpriced_observation_count
        )}
        icon={DollarSign}
        color="warning"
        scrollToId={hasCostByModel ? 'cost-by-model' : undefined}
      />
    </div>
  )
}

export function ExecutionDetail() {
  const { executionId } = useParams<{ executionId: string }>()
  const navigate = useNavigate()
  const { execution, artifactDetails, loading, error, isConnected, now, refreshExecution } =
    useExecutionData(executionId)

  if (loading) return <PageLoader />

  // Only the absence of data is a dead end. `error` on its own means the most
  // recent refresh failed, which the header reports without throwing away an
  // execution the page already has (#1048).
  if (!execution) {
    return (
      <Card>
        <EmptyState
          icon={Play}
          title="Execution not found"
          description={error || `Could not find execution with ID: ${executionId}`}
          action={{ label: 'Back to Workflows', onClick: () => navigate('/workflows') }}
        />
      </Card>
    )
  }

  const breadcrumbs: BreadcrumbItem[] = [
    { label: execution.workflow_name || execution.workflow_id, href: `/workflows/${execution.workflow_id}` },
    { label: `Execution ${execution.workflow_execution_id.slice(0, 8)}` },
  ]
  const aggregatedCostByModel = aggregateCostByModel(execution.phases)
  const tokens = executionTokenTotals(execution)

  return (
    <div className="space-y-6">
      <Breadcrumbs items={breadcrumbs} />
      <ExecutionHeader execution={execution} executionId={executionId} isConnected={isConnected} refreshError={error} now={now} refreshExecution={refreshExecution} />
      {execution.error_message && (
        <ExecutionErrorCard
          message={execution.error_message}
          status={execution.status}
          failureClassification={execution.failure_classification}
          reportedFailureReason={execution.reported_failure_reason}
        />
      )}
      <ReposPanel repos={execution.repos ?? []} />
      <ExecutionMetricsGrid
        execution={execution}
        hasCostByModel={Object.keys(aggregatedCostByModel).length > 0}
      />
      <section id="token-breakdown">
        <TokenBreakdown
          inputTokens={tokens.inputTokens}
          outputTokens={tokens.outputTokens}
          cacheCreationTokens={tokens.cacheCreationTokens}
          cacheReadTokens={tokens.cacheReadTokens}
          inProgressTokens={tokens.inProgressTokens}
          cacheReadRateDisplay={execution.cache_read_rate_display}
          cacheWriteRateDisplay={execution.cache_write_rate_display}
        />
      </section>
      {Object.keys(aggregatedCostByModel).length > 0 && (
        <section id="cost-by-model">
          <ModelBreakdown
            costByModel={aggregatedCostByModel}
            totalCost={execution.total_cost_usd}
            unpricedObservationCount={execution.unpriced_observation_count}
          />
        </section>
      )}
      <section id="phase-timeline">
        <PhaseTimeline execution={execution} now={now} />
      </section>
      {execution.artifact_ids.length > 0 && (
        <ArtifactSection phases={execution.phases} artifactDetails={artifactDetails} />
      )}
    </div>
  )
}
