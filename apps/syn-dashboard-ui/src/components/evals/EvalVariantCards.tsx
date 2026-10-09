import { clsx } from 'clsx'

import type { EvalVariant } from '../../api/evals'
import { JUDGED_UNAVAILABLE, STATS_UNAVAILABLE, judgedLabel, variantKey, type VariantCounts } from '../../utils/evalVariants'
import { EvalVariantLabel } from './EvalVariantLabel'

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-[var(--color-text-muted)]">{label}</dt>
      <dd className="break-words tabular-nums text-[var(--color-text-secondary)]">{value}</dd>
    </div>
  )
}

function VariantCard({ v, best, counts }: { v: EvalVariant; best: boolean; counts: VariantCounts }) {
  const s = v.stats
  return (
    <li
      data-best={best || undefined}
      className={clsx('break-all p-3 text-sm', best && 'bg-emerald-500/5 shadow-[inset_3px_0_0_#10b981]')}
    >
      <EvalVariantLabel v={v} best={best} counts={counts} />
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 break-normal">
        <Figure label="Pass rate" value={v.pass_rate_display} />
        <Figure label="Judged" value={judgedLabel(v, counts) ?? JUDGED_UNAVAILABLE} />
        <Figure label="Median duration" value={s?.median_duration_display ?? STATS_UNAVAILABLE} />
        <Figure label="Median cost" value={s?.median_cost_display ?? STATS_UNAVAILABLE} />
        <Figure label="Cost per PASS" value={s?.cost_per_pass_display ?? STATS_UNAVAILABLE} />
        <Figure label="Runs" value={String(v.run_count)} />
      </dl>
    </li>
  )
}

/** The Compare table as one card per variant, for a phone: every figure visible without a sideways swipe. */
export function EvalVariantCards({
  variants,
  best,
  counts,
}: {
  variants: readonly EvalVariant[]
  best: string | null
  counts: VariantCounts
}) {
  return (
    <ul aria-label="Variants" className="divide-y divide-[var(--color-border)]">
      {variants.map((v) => (
        <VariantCard key={variantKey(v)} v={v} best={variantKey(v) === best} counts={counts} />
      ))}
    </ul>
  )
}
