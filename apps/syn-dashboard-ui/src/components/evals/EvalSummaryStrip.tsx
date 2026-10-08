import type { EvalSummary } from '../../api/evals'
import { MetricCard } from '../MetricCard'

/**
 * The eval in five numbers, every one the server's figure over ALL of its
 * current runs (not the page of runs shown below), so the strip and the
 * Compare table can never disagree.
 */
export function EvalSummaryStrip({ e }: { e: EvalSummary }) {
  return (
    <section aria-label="Summary" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <MetricCard title="Pass rate" value={e.pass_rate_display} subtitle="PASS of PASS + FAIL; ERROR and unscored excluded" />
      <MetricCard title="Runs scored" value={`${e.scored_count} / ${e.run_count}`} subtitle={`over all ${e.run_count} runs`} />
      <MetricCard title="Median duration" wrap value={e.stats.median_duration_display} subtitle="per run" />
      <MetricCard title="Median cost" wrap value={e.stats.median_cost_display} subtitle="per run" />
      <MetricCard title="Cost per PASS" wrap value={e.stats.cost_per_pass_display} subtitle="all spend ÷ PASS runs" />
    </section>
  )
}
