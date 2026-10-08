<!--
  Trend Chart (Eval board): one line per series over shared dates, a dot per
  run, labels at the line ends, optional threshold and change markers. Lines
  are SVG stretched to the plot; dots, ticks and labels are HTML laid over
  it in the same percentages, so text never stretches. Geometry comes from
  skyline-core (evalTrendModel); this only renders it.
-->
<script lang="ts">
  import type { TrendChartProps } from './types'

  let {
    lines,
    dots,
    ends,
    yTicks,
    xTicks = [],
    notes = [],
    noteLabels = false,
    threshold = null,
    viewHeight,
    selected = -1,
    hair = null,
    size = 'lg',
    onpick,
    ...rest
  }: TrendChartProps = $props()

  const pick = (i: number) => () => onpick?.(i)
</script>

<div {...rest} class="sky-trend" data-size={size} data-notes={noteLabels && notes.length ? '' : undefined}>
  <div class="sky-trend__y" aria-hidden="true">
    {#each yTicks as t (t.at)}<span style:top={`${t.at}%`}>{t.label}</span>{/each}
  </div>
  <div class="sky-trend__body">
    <div class="sky-trend__plot">
      <svg viewBox={`0 0 1000 ${viewHeight}`} preserveAspectRatio="none" aria-hidden="true">
        {#each yTicks as t (t.at)}
          <line x1="0" x2="1000" y1={(t.at / 100) * viewHeight} y2={(t.at / 100) * viewHeight} class="sky-trend__grid" data-base={t.at >= 100 ? '' : undefined} vector-effect="non-scaling-stroke" />
        {/each}
        {#each lines as l (l.key)}
          <path d={l.d} class="sky-trend__line" data-color={l.color} vector-effect="non-scaling-stroke" />
        {/each}
      </svg>
      {#if threshold}
        <span class="sky-trend__threshold" style:top={`${threshold.top}%`} aria-hidden="true"></span>
        <span class="sky-trend__threshold-label" style:top={`${threshold.top}%`}>{threshold.label}</span>
      {/if}
      {#each notes as n (n.label)}
        <span class="sky-trend__note" style:left={`${n.x}%`} aria-hidden="true"></span>
        {#if noteLabels}<span class="sky-trend__note-label" style:left={`${n.x}%`}>{n.label}</span>{/if}
      {/each}
      {#if hair !== null}<span class="sky-trend__hair" style:left={`${hair}%`} aria-hidden="true"></span>{/if}
      {#each dots as d (d.i)}
        <button
          type="button"
          class="sky-trend__dot"
          data-color={d.color}
          aria-label={d.label}
          aria-pressed={d.i === selected}
          style:left={`${d.x}%`}
          style:top={`${d.top}%`}
          onpointerenter={pick(d.i)}
          onfocus={pick(d.i)}
          onclick={pick(d.i)}
        ><span></span></button>
      {/each}
    </div>
    {#if xTicks.length}
      <div class="sky-trend__x" aria-hidden="true">
        {#each xTicks as t (t.at)}<span style:left={`${t.at}%`}>{t.label}</span>{/each}
      </div>
    {/if}
  </div>
  <div class="sky-trend__ends">
    {#each ends as e (e.key)}
      <span style:top={`${e.top}%`} data-color={e.color}><span aria-hidden="true"></span>{e.label}</span>
    {/each}
  </div>
</div>

<style>
  .sky-trend {
    --sky-trend-h: 10.625rem;
    display: grid;
    grid-template-columns: 2.5rem minmax(0, 1fr) 4rem;
    column-gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-trend[data-size='md'] {
    --sky-trend-h: 8.125rem;
  }
  .sky-trend[data-notes] {
    padding-top: 1.875rem;
  }
  [data-color='1'] {
    --sky-trend-c: var(--sky-color-series-1);
  }
  [data-color='2'] {
    --sky-trend-c: var(--sky-color-series-2);
  }
  [data-color='3'] {
    --sky-trend-c: var(--sky-color-series-3);
  }
  [data-color='4'] {
    --sky-trend-c: var(--sky-color-series-4);
  }
  .sky-trend__y,
  .sky-trend__ends {
    position: relative;
    height: var(--sky-trend-h);
  }
  .sky-trend__y span {
    position: absolute;
    right: 0;
    transform: translateY(-50%);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-subtle);
    white-space: nowrap;
  }
  .sky-trend__body {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-trend__plot {
    position: relative;
    height: var(--sky-trend-h);
  }
  .sky-trend__plot svg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    overflow: visible;
  }
  .sky-trend__grid {
    stroke: var(--sky-color-grid);
    stroke-width: 1;
  }
  .sky-trend__grid[data-base] {
    stroke: var(--sky-color-border-strong);
  }
  .sky-trend__line {
    fill: none;
    stroke: var(--sky-trend-c);
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .sky-trend__threshold {
    position: absolute;
    left: 0;
    right: 0;
    height: 0;
    border-top: 1px dashed color-mix(in oklab, var(--ds-color-accent) 55%, var(--sky-color-border-strong));
  }
  .sky-trend__threshold-label {
    position: absolute;
    left: 6px;
    transform: translateY(-120%);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    color: var(--sky-color-accent-soft-fg);
  }
  .sky-trend__note {
    position: absolute;
    top: -6px;
    bottom: 0;
    width: 0;
    border-left: 1px dashed var(--sky-color-border-hover);
  }
  .sky-trend__note-label {
    position: absolute;
    top: -1.875rem;
    transform: translateX(-50%);
    height: 1.375rem;
    padding: 0 9px;
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-surface-raised);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    line-height: 1.25rem;
    color: var(--sky-color-text-code);
    white-space: nowrap;
  }
  .sky-trend__hair {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 0;
    border-left: 1px solid var(--sky-color-border-hover);
  }
  .sky-trend__dot {
    position: absolute;
    z-index: 2;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2.25rem;
    height: 2.25rem;
    margin: -1.125rem 0 0 -1.125rem;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: transparent;
    cursor: pointer;
  }
  .sky-trend__dot span {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--sky-trend-c);
    box-shadow: 0 0 0 2px var(--ds-color-surface);
  }
  .sky-trend__dot[aria-pressed='true'] {
    z-index: 3;
  }
  .sky-trend__dot[aria-pressed='true'] span {
    width: 14px;
    height: 14px;
    box-shadow:
      0 0 0 3px var(--ds-color-surface),
      0 0 0 5px var(--sky-trend-c);
  }
  .sky-trend__dot:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-trend__x {
    position: relative;
    height: 1rem;
  }
  .sky-trend__x span {
    position: absolute;
    transform: translateX(-50%);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-subtle);
    white-space: nowrap;
  }
  .sky-trend__ends > span {
    position: absolute;
    left: 4px;
    transform: translateY(-50%);
    display: flex;
    align-items: center;
    gap: 5px;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--sky-color-text-code);
    white-space: nowrap;
  }
  .sky-trend__ends > span > span {
    width: 10px;
    height: 3px;
    border-radius: 2px;
    background: var(--sky-trend-c);
  }
  @media (pointer: coarse) {
    .sky-trend__dot {
      width: var(--sky-size-touch);
      height: var(--sky-size-touch);
      margin: calc(var(--sky-size-touch) / -2) 0 0 calc(var(--sky-size-touch) / -2);
    }
  }
  @media (min-width: 48rem) {
    .sky-trend {
      --sky-trend-h: 12.5rem;
      grid-template-columns: 3rem minmax(0, 1fr) 5.25rem;
    }
    .sky-trend[data-size='md'] {
      --sky-trend-h: 9.375rem;
    }
    .sky-trend__dot {
      width: 1.75rem;
      height: 1.75rem;
      margin: -0.875rem 0 0 -0.875rem;
    }
  }
</style>
