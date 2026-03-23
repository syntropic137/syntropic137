import { clsx } from 'clsx'
import { Clock } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Card, CardContent, CardHeader } from '../../components'
import type { ArtifactResponse, ExecutionDetailResponse } from '../../types'
import { phaseStatusColors, phaseStatusIcons } from './executionConstants'

interface PhaseTimelineProps {
  phases: ExecutionDetailResponse['phases']
  now: number
  artifactDetails: Record<string, ArtifactResponse>
}

export function PhaseTimeline({ phases, now }: PhaseTimelineProps) {
  return (
    <Card>
      <CardHeader title="Phase Pipeline" subtitle="Execution phases with per-phase metrics" />
      <CardContent>
        <div className="flex items-center gap-2 overflow-x-auto pb-2">
          {phases.map((phase, idx) => {
            const Icon = phaseStatusIcons[phase.status] ?? Clock
            const phaseTokens = phase.input_tokens + phase.output_tokens

            return (
              <div key={phase.workflow_phase_id} className="flex items-center">
                <div
                  className={clsx(
                    'flex min-w-[200px] flex-col rounded-lg border p-4 transition-all',
                    phaseStatusColors[phase.status] ?? phaseStatusColors.pending
                  )}
                >
                  <div className="flex items-center gap-2">
                    <Icon className={clsx(
                      'h-4 w-4',
                      phase.status === 'completed' && 'text-emerald-400',
                      phase.status === 'running' && 'text-blue-400',
                      phase.status === 'failed' && 'text-red-400',
                      phase.status === 'pending' && 'text-slate-400'
                    )} />
                    <span className="text-sm font-medium text-[var(--color-text-primary)]">
                      {phase.name}
                    </span>
                  </div>
                  <div className="mt-3 space-y-1 text-xs text-[var(--color-text-muted)]">
                    <div className="flex justify-between">
                      <span>Tokens:</span>
                      <span className="text-[var(--color-text-secondary)]">{phaseTokens.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Cost:</span>
                      <span className="text-[var(--color-text-secondary)]">${Number(phase.cost_usd).toFixed(4)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Duration:</span>
                      <span className="text-[var(--color-text-secondary)]">
                        {phase.status === 'running' && phase.started_at
                          ? `${((now - new Date(phase.started_at).getTime()) / 1000).toFixed(1)}s`
                          : `${phase.duration_seconds.toFixed(1)}s`
                        }
                      </span>
                    </div>
                  </div>
                  {phase.session_id && (
                    <Link
                      to={`/sessions/${phase.session_id}`}
                      className="mt-3 text-xs text-[var(--color-accent)] hover:underline"
                    >
                      View Session →
                    </Link>
                  )}
                  {phase.agent_session_id && (
                    <div className="mt-1 text-xs text-[var(--color-text-muted)]">
                      <span title="Claude CLI session ID for OTel correlation">
                        OTel: {phase.agent_session_id.slice(0, 8)}...
                      </span>
                    </div>
                  )}
                </div>
                {idx < phases.length - 1 && (
                  <div className="mx-2 h-px w-8 bg-[var(--color-border)]" />
                )}
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
