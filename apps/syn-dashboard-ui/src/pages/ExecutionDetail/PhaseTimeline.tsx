import { clsx } from 'clsx'
import { Clock, DollarSign, Layers, Zap } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Card, CardContent, CardHeader } from '../../components'
import type { ExecutionDetailResponse } from '../../types'
import { executionTokenTotals, phaseTokenTotals } from '../../utils/executionTokens'
import { formatCostWithCoverage, formatTokens, liveDurationSeconds } from '../../utils/formatters'
import { phaseStatusColors, phaseStatusIcons } from './executionConstants'

function PhaseModelBreakdown({ costByModel }: { costByModel: Record<string, string> }) {
  const entries = Object.entries(costByModel)
    .map(([model, cost]) => ({ model, cost: parseFloat(cost) }))
    .sort((a, b) => b.cost - a.cost)
  const totalCost = entries.reduce((s, e) => s + e.cost, 0)

  return (
    <div className="mt-2 space-y-1">
      {entries.map(({ model, cost }) => {
        const pct = totalCost > 0 ? (cost / totalCost) * 100 : 0
        const shortName = model.replace(/^claude-/, '').replace(/-\d{8}$/, '')
        return (
          <div key={model} className="space-y-0.5">
            <div className="flex items-center justify-between text-[10px]">
              <span className="font-mono text-[var(--color-text-muted)]">{shortName}</span>
              <span className="text-[var(--color-text-secondary)]">
                ${cost.toFixed(4)} &middot; {pct.toFixed(0)}%
              </span>
            </div>
            <div className="h-1 bg-[var(--color-surface-elevated)] rounded-full overflow-hidden">
              <div className="h-full bg-indigo-500 rounded-full transition-all" style={{ width: `${Math.max(pct, 1)}%` }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

type Phase = ExecutionDetailResponse['phases'][number]

const statusIconColors: Record<string, string> = {
  completed: 'text-emerald-400',
  running: 'text-blue-400',
  failed: 'text-red-400',
  pending: 'text-slate-400',
}

function PhaseTokenSegment({ label, total, rows, accentColor }: {
  label: string; total: number; accentColor: string
  rows: { label: string; value: number; color?: string }[]
}) {
  return (
    <div className="rounded-md border border-[var(--color-border)] overflow-hidden">
      <div className={`flex items-center justify-between px-2 py-1 ${accentColor}`}>
        <span className="font-medium">{label}</span>
        <span className="text-[var(--color-text-secondary)]">{total.toLocaleString()}</span>
      </div>
      <div className="px-2 py-1 space-y-0.5">
        {rows.map(r => (
          <div key={r.label} className="flex justify-between">
            <span className={r.color ?? ''}>{r.label}</span>
            <span className={r.color ?? 'text-[var(--color-text-secondary)]'}>{r.value.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function PhaseCardBody({ phase, now }: { phase: Phase; now: number }) {
  const Icon = phaseStatusIcons[phase.status] ?? Clock
  const tokens = phaseTokenTotals(phase)
  // `duration_seconds` is nullable: the server returns null for a genuinely
  // unknown duration rather than a 0.0 that looks like a real measurement.
  // `liveDurationSeconds` keeps the running case ticking between polls while
  // deferring to that value whenever the live reading is not measurable.
  const durationSeconds = liveDurationSeconds(
    phase.status === 'running',
    phase.started_at,
    phase.duration_seconds,
    now,
  )
  const duration = durationSeconds === null ? '—' : `${durationSeconds.toFixed(1)}s`

  return (
    <>
      <div className="flex items-center gap-2">
        <Icon className={clsx('h-4 w-4', statusIconColors[phase.status] ?? 'text-slate-400')} />
        <span className="text-sm font-medium text-[var(--color-text-primary)]">{phase.name}</span>
      </div>
      {phase.cost_by_model && Object.keys(phase.cost_by_model).length > 0 && (
        <PhaseModelBreakdown costByModel={phase.cost_by_model} />
      )}
      <div className="mt-2 flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
        {/*
          A running phase's counts are a lower bound, not a reading: the API has
          no live per-phase token field, so the figures below stay at 0 (or at a
          part-substituted cache figure) until the phase lands. Saying "so far"
          is the difference between an incomplete count and a claim of none.
        */}
        <span title={tokens.settled ? undefined : 'Counted so far; this phase is still running'}>
          {tokens.settled ? formatTokens(tokens.total) : `${formatTokens(tokens.total)} so far`}
        </span>
        <span className="text-[var(--color-border)]">&middot;</span>
        <span>
          {formatCostWithCoverage(Number(phase.cost_usd), phase.unpriced_observation_count)}
        </span>
        <span className="text-[var(--color-border)]">&middot;</span>
        <span>{duration}</span>
      </div>
      <div className="mt-2 space-y-1.5 text-xs text-[var(--color-text-muted)]">
        <PhaseTokenSegment
          label="In"
          total={tokens.inputTokens + tokens.cacheReadTokens}
          accentColor="bg-indigo-500/10 text-indigo-400"
          rows={[
            { label: 'Fresh', value: tokens.inputTokens },
            { label: 'Cache read', value: tokens.cacheReadTokens, color: 'text-emerald-400' },
          ]}
        />
        <PhaseTokenSegment
          label="Out"
          total={tokens.outputTokens + tokens.cacheCreationTokens}
          accentColor="bg-violet-500/10 text-violet-400"
          rows={[
            { label: 'Output', value: tokens.outputTokens },
            { label: 'Cache write', value: tokens.cacheCreationTokens, color: 'text-amber-400' },
          ]}
        />
      </div>
      {phase.agent_session_id && (
        <div className="mt-auto pt-2 text-xs text-[var(--color-text-muted)]">
          <span title="Claude CLI session ID for OTel correlation">
            OTel: {phase.agent_session_id.slice(0, 8)}...
          </span>
        </div>
      )}
    </>
  )
}

function PhaseCard({ phase, now }: { phase: Phase; now: number }) {
  const baseClasses = clsx(
    'flex min-w-[200px] flex-1 flex-col rounded-lg border p-4 transition-all',
    phaseStatusColors[phase.status] ?? phaseStatusColors.pending,
  )
  if (phase.session_id) {
    return (
      <Link
        to={`/sessions/${phase.session_id}`}
        className={clsx(
          baseClasses,
          'cursor-pointer hover:border-[var(--color-accent)] hover:shadow-md focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]',
        )}
        aria-label={`Open session for phase ${phase.name}`}
      >
        <PhaseCardBody phase={phase} now={now} />
      </Link>
    )
  }
  return (
    <div className={baseClasses}>
      <PhaseCardBody phase={phase} now={now} />
    </div>
  )
}

interface PhaseTimelineProps {
  /**
   * The whole payload, not just `phases`: the header's token roll-up has to
   * come from the execution-level total, which the phases cannot produce.
   * Passing the execution keeps that choice inside this component, so a caller
   * cannot render the timeline against a total derived some other way.
   */
  execution: ExecutionDetailResponse
  now: number
}

export function PhaseTimeline({ execution, now }: PhaseTimelineProps) {
  const phases = execution.phases
  // Read from the execution, not from the phases below. Lane 1 leaves a running
  // phase's counts at 0, so a roll-up summed from the cards reported "0 tokens"
  // for the whole of a live run - directly under a headline card already
  // showing the live figure (#1048). Both now read executionTokenTotals().
  const totalTokens = executionTokenTotals(execution).total
  // Cost follows tokens: read the execution, not the phases. On the live path
  // the domain builds an empty cost_by_phase map, so every phase is seeded
  // cost_usd=0 and only overwritten once a summary exists. Summing the cards
  // therefore printed a confident "$0.000000" directly beneath a Total Cost
  // card reading $0.42 (#1048).
  //
  // The unpriced count has to come from the same level for the same reason:
  // unpriced_by_phase is empty on that path too, so the #890 coverage signal
  // was zeroed out exactly when it was needed and the zero rendered as a
  // precise figure rather than as "unpriced".
  const totalCost = Number(execution.total_cost_usd)
  const totalUnpriced = execution.unpriced_observation_count
  // Duration, unlike cost, IS folded from the cards - deliberately. A running
  // phase's duration is derived live from started_at by the same helper the
  // card uses, so the phases are a true reading here and folding them keeps the
  // header from disagreeing with the timeline underneath it. Cost has no such
  // live per-phase value to fold, which is why it reads the execution instead.
  //
  // `?? 0` would still turn an UNKNOWN duration into a measured zero, so an
  // execution whose phases all report null would render a confident "0.0s" and
  // a partly-known one would read as complete. Count what is missing instead.
  const knownDurations = phases
    .map((p) => liveDurationSeconds(p.status === 'running', p.started_at, p.duration_seconds, now))
    .filter((d): d is number => d !== null)
  const totalDuration = knownDurations.reduce((s, d) => s + d, 0)
  const unknownDurations = phases.length - knownDurations.length

  return (
    <Card>
      <CardHeader title="Phase Pipeline" subtitle="Execution phases with per-phase metrics" />
      <CardContent>
        <div className="flex items-center gap-4 mb-4 text-sm text-[var(--color-text-secondary)]">
          <div className="flex items-center gap-1.5">
            <Layers className="h-4 w-4 text-[var(--color-text-muted)]" />
            <span className="font-medium">{phases.length} phases</span>
          </div>
          <span className="text-[var(--color-border)]">|</span>
          <div className="flex items-center gap-1.5">
            <Zap className="h-4 w-4 text-[var(--color-text-muted)]" />
            <span>{formatTokens(totalTokens)} tokens</span>
          </div>
          <span className="text-[var(--color-border)]">|</span>
          <div className="flex items-center gap-1.5">
            <DollarSign className="h-4 w-4 text-[var(--color-text-muted)]" />
            <span>{formatCostWithCoverage(totalCost, totalUnpriced)}</span>
          </div>
          <span className="text-[var(--color-border)]">|</span>
          <div className="flex items-center gap-1.5">
            <Clock className="h-4 w-4 text-[var(--color-text-muted)]" />
            <span>
              {knownDurations.length === 0
                ? '—'
                : `${totalDuration.toFixed(1)}s${unknownDurations > 0 ? ` (+${unknownDurations} unknown)` : ''}`}
            </span>
          </div>
        </div>
        <div className="flex items-stretch gap-2 overflow-x-auto pb-2">
          {phases.map((phase, idx) => (
            <div key={phase.workflow_phase_id} className="flex items-stretch">
              <PhaseCard phase={phase} now={now} />
              {idx < phases.length - 1 && (
                <div className="mx-2 h-px w-8 self-center bg-[var(--color-border)]" />
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
