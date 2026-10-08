<!--
  Outcome Ring (Main board Outcomes card, CompPatterns): the share of
  completed, failed and cancelled runs. The centre reads the completed
  percentage; the legend lists the counts. Arcs from layoutRing().
-->
<script lang="ts">
  import { OUTCOME_RING, layoutRing, percentOf } from '@syn137/skyline-core/geometry'
  import type { OutcomeRingProps } from './types'

  let { completed, failed, cancelled, noun = 'executions', legend = true, size = 120, ...rest }: OutcomeRingProps = $props()

  const parts = $derived([
    { key: 'completed' as const, value: completed, label: 'Completed' },
    { key: 'failed' as const, value: failed, label: 'Failed' },
    { key: 'cancelled' as const, value: cancelled, label: 'Cancelled' },
  ])
  const ring = $derived(layoutRing(parts))
  const total = $derived(ring.total)
  const pct = $derived(percentOf(completed, total))
  const summary = $derived(
    total === 0
      ? `No ${noun} yet`
      : [
          `${percentOf(completed, total)} percent of ${noun} completed`,
          failed ? `${percentOf(failed, total)} percent failed` : '',
          cancelled ? `${percentOf(cancelled, total)} percent were cancelled` : '',
        ]
          .filter(Boolean)
          .join(', '),
  )
  const d = OUTCOME_RING
  const c = d.size / 2
</script>

<section {...rest} class="sky-outcome" data-legend={legend || undefined} aria-label={rest['aria-label'] ?? 'Outcomes'}>
  <svg class="sky-outcome__ring" width={size} height={size} viewBox={`0 0 ${d.size} ${d.size}`} role="img" aria-label={summary}>
    <circle class="sky-outcome__track" cx={c} cy={c} r={d.radius} stroke-width={d.stroke} />
    <g transform={`rotate(-90 ${c} ${c})`} fill="none" stroke-width={d.stroke}>
      {#each ring.arcs as a (a.key)}
        <circle class="sky-outcome__arc" data-key={a.key} cx={c} cy={c} r={d.radius} stroke-dasharray={a.dasharray} stroke-dashoffset={a.dashoffset} />
      {/each}
    </g>
    <text class="sky-outcome__pct" x={c} y={legend ? c + 4 : c + 6} text-anchor="middle">{total ? `${pct}%` : '—'}</text>
    {#if legend}<text class="sky-outcome__caption" x={c} y={c + 19} text-anchor="middle">completed</text>{/if}
  </svg>
  {#if legend}
    <div class="sky-outcome__legend">
      <h2 class="sky-outcome__title">Outcomes · {total} {noun}</h2>
      {#each parts as p (p.key)}
        <div class="sky-outcome__row">
          <span class="sky-outcome__swatch" data-key={p.key}></span>
          <span class="sky-outcome__label">{p.label}</span>
          <span class="sky-outcome__value">{p.value}</span>
        </div>
      {/each}
    </div>
  {/if}
</section>

<style>
  .sky-outcome {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-6);
  }
  .sky-outcome__ring {
    display: block;
    flex-shrink: 0;
  }
  .sky-outcome__track {
    fill: none;
    stroke: var(--sky-color-control-hover);
  }
  .sky-outcome__arc[data-key='completed'],
  .sky-outcome__swatch[data-key='completed'] {
    stroke: var(--sky-status-completed);
    background: var(--sky-status-completed);
  }
  .sky-outcome__arc[data-key='failed'],
  .sky-outcome__swatch[data-key='failed'] {
    stroke: var(--sky-status-failed);
    background: var(--sky-status-failed);
  }
  .sky-outcome__arc[data-key='cancelled'],
  .sky-outcome__swatch[data-key='cancelled'] {
    stroke: var(--sky-status-cancelled);
    background: var(--sky-status-cancelled);
  }
  .sky-outcome__pct {
    font-size: 24px;
    font-weight: var(--ds-font-weight-semibold);
    fill: var(--ds-color-fg);
  }
  .sky-outcome__caption {
    font-family: var(--ds-font-mono);
    font-size: 9px;
    fill: var(--ds-color-text-muted);
  }
  .sky-outcome__legend {
    flex: 1 1 9.5rem;
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2-5);
  }
  .sky-outcome__title {
    margin: 0 0 2px;
    font-size: var(--sky-text-body);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-outcome__row {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2-5);
    font-size: var(--ds-text-sm);
  }
  .sky-outcome__swatch {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 2px;
  }
  .sky-outcome__label {
    flex-grow: 1;
    color: var(--ds-color-text-muted);
  }
  .sky-outcome__value {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
  }
</style>
