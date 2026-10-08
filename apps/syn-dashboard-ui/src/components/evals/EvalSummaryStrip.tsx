import type { EvalRunStats, EvalSummary } from '../../api/evals'
import { verdictBreakdown } from '../../utils/evalSummary'
import { MetricCard } from '../MetricCard'

function StatsCards({ stats }: { stats: EvalRunStats }) {
  return (
    <>
      <MetricCard title="Median duration" wrap value={stats.median_duration_display} subtitle="per run" />
      <MetricCard title="Median cost" wrap value={stats.median_cost_display} subtitle="per run" />
      <MetricCard
        title="Cost per PASS"
        wrap
        value={stats.cost_per_pass_display}
        subtitle="scored-run spend (ERROR included) ÷ PASS runs; unscored excluded"
      />
    </>
  )
}

/**
 * The eval in five numbers, every one the server's figure over ALL of its
 * current runs (not the page of runs shown below), so the strip and the
 * Compare table can never disagree. An API older than #1772 sends no stats:
 * the strip then says so instead of failing the page.
 */
export function EvalSummaryStrip({ e }: { e: EvalSummary }) {
  return (
    <section aria-label="Summary" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <MetricCard title="Pass rate" value={e.pass_rate_display} subtitle="PASS of PASS + FAIL; ERROR and unscored excluded" />
      <MetricCard
        title="Runs scored"
        wrap
        value={`${e.scored_count} / ${e.run_count}`}
        subtitle={e.stats ? verdictBreakdown(e.stats) : `over all ${e.run_count} runs`}
      />
      {e.stats ? (
        <StatsCards stats={e.stats} />
      ) : (
        <p className="col-span-2 self-center text-sm text-[var(--color-text-muted)] sm:col-span-1 lg:col-span-3">
          Stats unavailable: this API version reports no duration, cost or verdict breakdown.
        </p>
      )}
    </section>
  )
}
