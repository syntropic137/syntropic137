/**
 * One eval — composition only: what it asks, what it adds up to, how its
 * variants compare, whether they are improving, and every run.
 */

import { FlaskConical } from 'lucide-react'
import { useState } from 'react'
import { useParams } from 'react-router-dom'

import { Breadcrumbs, Card, CardHeader, EmptyState, ListPagination, Loader, PageLoader } from '../../components'
import { EvalHeader, EvalRunsChart, EvalRunsTable, EvalSummaryStrip, EvalVariantsTable } from '../../components/evals'
import { useEvalDetail } from '../../hooks/useEvalDetail'
import { useEvalTimeline, type EvalTimelineState } from '../../hooks/useEvalTimeline'
import { runsSubtitle } from '../../utils/evalSummary'

function timelineSubtitle(timeline: EvalTimelineState): string {
  if (timeline.kind !== 'ready') return 'Every run, by variant'
  if (timeline.runs.length < timeline.total) return `Latest ${timeline.runs.length} of ${timeline.total} runs, by variant`
  return `All ${timeline.total} runs, by variant`
}

function TimelineCard({ timeline }: { timeline: EvalTimelineState }) {
  return (
    <Card>
      <CardHeader title="Trend" subtitle={timelineSubtitle(timeline)} />
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
      <EvalSummaryStrip e={e} />
      <Card>
        <CardHeader title="Compare variants" subtitle={`Workflow × version × models, over all ${e.run_count} runs`} />
        <EvalVariantsTable variants={e.variants ?? []} />
      </Card>
      <TimelineCard timeline={timeline} />
      <Card>
        <CardHeader title="Runs" subtitle={runsSubtitle(state)} />
        <EvalRunsTable runs={state.runs} />
      </Card>
      <ListPagination page={state.page} pageSize={state.pageSize} total={state.total} onPageChange={setPage} itemLabel="run" />
    </div>
  )
}
