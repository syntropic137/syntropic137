import { clsx } from 'clsx'
import { Clock, DollarSign, Layers, Zap } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Card, CardContent, CardHeader } from '../../components'
import type { ExecutionDetailResponse } from '../../types'
import { formatTokens } from '../../utils/formatters'
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

function PhaseCard({ phase, now }: { phase: Phase; now: number }) {
  const Icon = phaseStatusIcons[phase.status] ?? Clock
  const totalPhaseTokens = phase.input_tokens + phase.output_tokens + (phase.cache_creation_tokens ?? 0) + (phase.cache_read_tokens ?? 0)
  const duration = phase.status === 'running' && phase.started_at
    ? ((now - new Date(phase.started_at).getTime()) / 1000).toFixed(1)
    : phase.duration_seconds.toFixed(1)

  return (
    <div className={clsx('flex min-w-[200px] flex-1 flex-col rounded-lg border p-4 transition-all', phaseStatusColors[phase.status] ?? phaseStatusColors.pending)}>
      <div className="flex items-center gap-2">
        <Icon className={clsx('h-4 w-4', statusIconColors[phase.status] ?? 'text-slate-400')} />
        <span className="text-sm font-medium text-[var(--color-text-primary)]">{phase.name}</span>
      </div>
      {phase.cost_by_model && Object.keys(phase.cost_by_model).length > 0 && (
        <PhaseModelBreakdown costByModel={phase.cost_by_model} />
      )}
      <div className="mt-2 flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
        <span>{formatTokens(totalPhaseTokens)}</span>
        <span className="text-[var(--color-border)]">&middot;</span>
        <span>${Number(phase.cost_usd).toFixed(4)}</span>
        <span className="text-[var(--color-border)]">&middot;</span>
        <span>{duration}s</span>
      </div>
      <div className="mt-2 space-y-1.5 text-xs text-[var(--color-text-muted)]">
        <PhaseTokenSegment label="In" total={phase.input_tokens + (phase.cache_read_tokens ?? 0)} accentColor="bg-indigo-500/10 text-indigo-400" rows={[
          { label: 'Fresh', value: phase.input_tokens },
          { label: 'Cache read', value: phase.cache_read_tokens ?? 0, color: 'text-emerald-400' },
        ]} />
        <PhaseTokenSegment label="Out" total={phase.output_tokens + (phase.cache_creation_tokens ?? 0)} accentColor="bg-violet-500/10 text-violet-400" rows={[
          { label: 'Output', value: phase.output_tokens },
          { label: 'Cache write', value: phase.cache_creation_tokens ?? 0, color: 'text-amber-400' },
        ]} />
      </div>
      <div className="mt-auto pt-2">
        {phase.session_id && (
          <Link to={`/sessions/${phase.session_id}`} className="text-xs text-[var(--color-accent)] hover:underline">
            View Session →
          </Link>
        )}
        {phase.agent_session_id && (
          <div className="mt-1 text-xs text-[var(--color-text-muted)]">
            <span title="Claude CLI session ID for OTel correlation">OTel: {phase.agent_session_id.slice(0, 8)}...</span>
          </div>
        )}
      </div>
    </div>
  )
}

interface PhaseTimelineProps {
  phases: ExecutionDetailResponse['phases']
  now: number
}

export function PhaseTimeline({ phases, now }: PhaseTimelineProps) {
  const totalTokens = phases.reduce((s, p) => s + p.input_tokens + p.output_tokens + (p.cache_creation_tokens ?? 0) + (p.cache_read_tokens ?? 0), 0)
  const totalCost = phases.reduce((s, p) => s + Number(p.cost_usd), 0)
  const totalDuration = phases.reduce((s, p) => s + p.duration_seconds, 0)

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
            <span>${totalCost.toFixed(4)}</span>
          </div>
          <span className="text-[var(--color-border)]">|</span>
          <div className="flex items-center gap-1.5">
            <Clock className="h-4 w-4 text-[var(--color-text-muted)]" />
            <span>{totalDuration.toFixed(1)}s</span>
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
