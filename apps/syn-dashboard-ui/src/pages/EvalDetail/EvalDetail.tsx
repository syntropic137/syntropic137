/**
 * One eval — composition only: what it asks, how its variants compare, and
 * every run over time.
 */

import { FlaskConical, Lock } from 'lucide-react'
import { useState } from 'react'
import { useParams } from 'react-router-dom'

import type { EvalSummary } from '../../api/evals'
import { Breadcrumbs, Card, CardHeader, EmptyState, ListPagination, Loader, PageLoader } from '../../components'
import { EvalRunsChart, EvalRunsTable, EvalVariantsTable } from '../../components/evals'
import { useEvalDetail } from '../../hooks/useEvalDetail'
import { useEvalTimeline, type EvalTimelineState } from '../../hooks/useEvalTimeline'

function EvalHeader({ e }: { e: EvalSummary }) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="min-w-0 break-words text-2xl font-bold text-[var(--color-text-primary)]">{e.name}</h1>
        {e.frozen && (
          <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/10 px-2 py-0.5 text-xs text-sky-400">
            <Lock className="h-3 w-3" /> Frozen
          </span>
        )}
      </div>
      <p className="whitespace-pre-wrap break-words text-sm text-[var(--color-text-secondary)]">{e.goal}</p>
      <ul className="space-y-0.5 text-xs text-[var(--color-text-muted)]" aria-label="Baseline">
        {e.baseline_repos.map((repo) => (
          <li key={repo.repository} className="break-all">
            Baseline{' '}
            <a
              href={`https://github.com/${repo.repository}/tree/${repo.commit_sha}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--color-accent)] hover:underline"
            >
              {repo.repository}@{repo.commit_sha.slice(0, 12)}
            </a>{' '}
            ({repo.requested_ref})
          </li>
        ))}
      </ul>
      {e.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {e.tags.map((tag) => (
            <span key={tag} className="break-all rounded-full bg-[var(--color-accent)]/10 px-2 py-0.5 text-[11px] text-[var(--color-accent)]">
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function timelineSubtitle(timeline: EvalTimelineState): string {
  if (timeline.kind !== 'ready') return 'Every run, by variant'
  if (timeline.runs.length < timeline.total) return `Latest ${timeline.runs.length} of ${timeline.total} runs, by variant`
  return `All ${timeline.total} runs, by variant`
}

function TimelineCard({ timeline }: { timeline: EvalTimelineState }) {
  return (
    <Card>
      <CardHeader title="Runs over time" subtitle={timelineSubtitle(timeline)} />
      {timeline.kind === 'loading' && <Loader className="p-4" />}
      {timeline.kind === 'error' && (
        <p className="p-4 text-sm text-[var(--color-text-muted)]">Could not load the run history: {timeline.message}</p>
      )}
      {timeline.kind === 'ready' && <EvalRunsChart runs={timeline.runs} />}
    </Card>
  )
}

export function EvalDetail() {
  const { evalId } = useParams<{ evalId: string }>()
  const [page, setPage] = useState(1)
  const state = useEvalDetail(evalId, page)
  const timeline = useEvalTimeline(evalId)

  if (state.kind === 'loading') return <PageLoader />
  if (state.kind === 'error') {
    return (
      <Card>
        <EmptyState icon={FlaskConical} title="Could not load this eval" description={state.message} />
      </Card>
    )
  }

  const e = state.eval
  return (
    <div className="min-w-0 space-y-6">
      <Breadcrumbs items={[{ label: 'Evals', href: '/evals' }, { label: e.name }]} />
      <EvalHeader e={e} />
      <Card>
        <CardHeader title="Compare" subtitle={`${e.run_count} runs · ${e.scored_count} scored · pass rate ${e.pass_rate_display}`} />
        <EvalVariantsTable variants={e.variants} />
      </Card>
      <TimelineCard timeline={timeline} />
      <Card>
        <CardHeader title="Runs" />
        <EvalRunsTable runs={state.runs} />
      </Card>
      <ListPagination page={state.page} pageSize={state.pageSize} total={state.total} onPageChange={setPage} itemLabel="run" />
    </div>
  )
}
