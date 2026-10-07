/**
 * Evals page — composition only.
 *
 * One row per eval: what it asks, how often it has passed lately, and which
 * workflow and model combinations it has been run with.
 */

import { FlaskConical, X } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'

import { Card, EmptyState, PageLoader } from '../../components'
import { EvalVariantsStrip, VerdictSparkline } from '../../components/evals'
import { useEvalList, type EvalListRow } from '../../hooks/useEvalList'
import { formatRelativeTime } from '../../utils/dateFormatters'

function TagButton({ tag, onSelect }: { tag: string; onSelect: (tag: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(tag)}
      className="max-w-full break-all rounded-full bg-[var(--color-accent)]/10 px-2 py-0.5 text-[11px] text-[var(--color-accent)] hover:bg-[var(--color-accent)]/20"
    >
      {tag}
    </button>
  )
}

function EvalRow({ row, onTag }: { row: EvalListRow; onTag: (tag: string) => void }) {
  const e = row.eval
  return (
    <li className="space-y-2 border-b border-[var(--color-border)] p-4 last:border-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <Link
          to={`/evals/${e.eval_id}`}
          className="min-w-0 break-words font-medium text-[var(--color-text-primary)] hover:text-[var(--color-accent)]"
        >
          {e.name}
        </Link>
        <div className="flex items-center gap-3 text-xs text-[var(--color-text-secondary)]">
          <span className="tabular-nums">
            {e.run_count} {e.run_count === 1 ? 'run' : 'runs'}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <VerdictSparkline verdicts={row.recentVerdicts} />
            <span className="tabular-nums text-[var(--color-text-primary)]" title="Pass rate of scored runs">
              {e.pass_rate_display}
            </span>
          </span>
          <span title={e.last_run_at ?? undefined}>{formatRelativeTime(e.last_run_at)}</span>
        </div>
      </div>
      <p className="line-clamp-2 break-words text-sm text-[var(--color-text-secondary)]">{e.goal}</p>
      {e.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {e.tags.map((tag) => (
            <TagButton key={tag} tag={tag} onSelect={onTag} />
          ))}
        </div>
      )}
      <EvalVariantsStrip variants={e.variants} />
    </li>
  )
}

export function EvalList() {
  const [params, setParams] = useSearchParams()
  const tag = params.get('tag')
  const state = useEvalList(tag)
  const setTag = (next: string | null) => setParams(next ? { tag: next } : {})

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Evals</h1>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          Stable cases run again and again, so the same goal can be compared across workflows and models over time
          {state.kind === 'ready' && state.total > 0 && (
            <span className="text-[var(--color-text-muted)]"> · {state.total} evals</span>
          )}
        </p>
      </div>

      {tag && (
        <div className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
          Tagged
          <button
            type="button"
            onClick={() => setTag(null)}
            aria-label={`Clear tag filter ${tag}`}
            className="inline-flex max-w-full items-center gap-1 break-all rounded-full bg-[var(--color-accent)]/10 px-2 py-0.5 text-xs text-[var(--color-accent)]"
          >
            {tag}
            <X className="h-3 w-3 shrink-0" />
          </button>
        </div>
      )}

      {state.kind === 'loading' ? (
        <PageLoader />
      ) : state.kind === 'error' ? (
        <Card>
          <EmptyState icon={FlaskConical} title="Could not load evals" description={state.message} />
        </Card>
      ) : state.rows.length === 0 ? (
        <Card>
          <EmptyState
            icon={FlaskConical}
            title={tag ? `No evals tagged ${tag}` : 'No evals yet'}
            description="Create one with `scripts/eval_suite.py launch`, or POST /evals with a goal and a pinned baseline repo. Each execution launched into it becomes a run here."
          />
        </Card>
      ) : (
        <Card>
          <ul>
            {state.rows.map((row) => (
              <EvalRow key={row.eval.eval_id} row={row} onTag={setTag} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
