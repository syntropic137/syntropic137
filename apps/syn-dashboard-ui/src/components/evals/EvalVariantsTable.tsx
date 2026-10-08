import { clsx } from 'clsx'
import { useState } from 'react'

import type { EvalVariant } from '../../api/evals'
import { useIsMobile } from '../../hooks/useMediaQuery'
import { formatRelativeTime } from '../../utils/dateFormatters'
import {
  bestVariantKey,
  judgedLabel,
  sortVariants,
  STATS_UNAVAILABLE,
  variantKey,
  type VariantSortDir,
  type VariantSortKey,
} from '../../utils/evalVariants'
import { EvalVariantCards } from './EvalVariantCards'
import { EvalVariantLabel } from './EvalVariantLabel'

const COLUMNS: { key: VariantSortKey; label: string; firstDir: VariantSortDir }[] = [
  { key: 'runs', label: 'Runs', firstDir: 'desc' },
  { key: 'pass_rate', label: 'Pass rate', firstDir: 'desc' },
  { key: 'duration', label: 'Median duration', firstDir: 'asc' },
  { key: 'cost', label: 'Median cost', firstDir: 'asc' },
  { key: 'last_run', label: 'Last run', firstDir: 'desc' },
]

interface Sort {
  key: VariantSortKey
  dir: VariantSortDir
}

function SortHeader({ column, sort, onSort }: { column: (typeof COLUMNS)[number]; sort: Sort; onSort: (s: Sort) => void }) {
  const active = sort.key === column.key
  const flipped: VariantSortDir = sort.dir === 'asc' ? 'desc' : 'asc'
  return (
    <th
      className="px-3 py-2 text-right font-medium"
      aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        type="button"
        className={clsx('whitespace-nowrap hover:text-[var(--color-text-primary)]', active && 'text-[var(--color-text-primary)]')}
        onClick={() => onSort({ key: column.key, dir: active ? flipped : column.firstDir })}
      >
        {column.label}
        {active ? (sort.dir === 'asc' ? ' ↑' : ' ↓') : ''}
      </button>
    </th>
  )
}

function VariantRow({ v, best }: { v: EvalVariant; best: boolean }) {
  const cell = 'px-3 py-2 text-right tabular-nums text-[var(--color-text-secondary)]'
  const s = v.stats
  return (
    <tr
      data-best={best || undefined}
      className={clsx('border-b border-[var(--color-border)] last:border-0', best && 'bg-emerald-500/5 shadow-[inset_3px_0_0_#10b981]')}
    >
      <td className="break-all px-3 py-2">
        <EvalVariantLabel v={v} best={best} />
      </td>
      <td className={cell}>{v.run_count}</td>
      <td className={clsx(cell, 'text-[var(--color-text-primary)]')}>
        {v.pass_rate_display}
        <div className="text-[11px] text-[var(--color-text-muted)]">{judgedLabel(v) ?? STATS_UNAVAILABLE}</div>
      </td>
      <td className={cell}>{s?.median_duration_display ?? STATS_UNAVAILABLE}</td>
      <td className={cell}>
        {s?.median_cost_display ?? STATS_UNAVAILABLE}
        {s && <div className="text-[11px] text-[var(--color-text-muted)]">{s.cost_per_pass_display} / PASS</div>}
      </td>
      <td className={cell} title={v.last_run_at ?? undefined}>
        {formatRelativeTime(v.last_run_at)}
      </td>
    </tr>
  )
}

function VariantsTable({ variants, best }: { variants: readonly EvalVariant[]; best: string | null }) {
  const [sort, setSort] = useState<Sort>({ key: 'pass_rate', dir: 'desc' })
  return (
    <div className="overflow-x-auto" data-testid="variants-scroll">
      <table className="w-full min-w-[40rem] table-fixed text-sm">
        <thead>
          <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
            <th className="w-[34%] px-3 py-2 font-medium">Variant · last verdict</th>
            {COLUMNS.map((c) => (
              <SortHeader key={c.key} column={c} sort={sort} onSort={setSort} />
            ))}
          </tr>
        </thead>
        <tbody>
          {sortVariants(variants, sort.key, sort.dir).map((v) => (
            <VariantRow key={variantKey(v)} v={v} best={variantKey(v) === best} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * The Compare view: one entry per (workflow, workflow version, observed
 * models) variant, with the best one marked. Every figure is the server's,
 * over all of the eval's runs. A sortable table on a wide screen; on a phone,
 * one card per variant (by pass rate), so no figure hides behind a swipe.
 */
export function EvalVariantsTable({ variants }: { variants: readonly EvalVariant[] }) {
  const isMobile = useIsMobile()
  if (variants.length === 0) {
    return <p className="p-4 text-sm text-[var(--color-text-muted)]">No runs yet, so nothing to compare.</p>
  }
  const best = bestVariantKey(variants)
  if (isMobile) return <EvalVariantCards variants={sortVariants(variants, 'pass_rate', 'desc')} best={best} />
  return <VariantsTable variants={variants} best={best} />
}

/** The same comparison squeezed into one line per variant, for the eval list. */
export function EvalVariantsStrip({ variants }: { variants: readonly EvalVariant[] }) {
  if (variants.length === 0) return null
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Variants">
      {variants.map((v) => (
        <li
          key={variantKey(v)}
          className="min-w-0 max-w-full break-all rounded bg-[var(--color-surface-elevated)] px-1.5 py-0.5 text-[11px] text-[var(--color-text-secondary)]"
        >
          {v.workflow_id}
          {v.workflow_version && <span className="text-[var(--color-text-muted)]"> @ {v.workflow_version}</span>}
          {v.models.length > 0 && <span className="text-[var(--color-text-muted)]"> · {v.models.join(', ')}</span>}
          {' → '}
          <span className="text-[var(--color-text-primary)]">{v.pass_rate_display}</span>
        </li>
      ))}
    </ul>
  )
}
