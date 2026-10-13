<!--
  Eval Explorer (Landing section 04; a compact Evals list mode later):
  quality and cost per run over time for each verifier, the ranking by
  quality per dollar, and a one-line verdict on the picked verifier
  (skyline-core explorerModel, rankVerdict). The window chrome around it
  belongs to the page.

  Keyboard: the ranking is a radio group. Tab reaches the picked row, the
  arrow keys move the pick in rank order (wrapping), Home and End jump to
  the first and last. Pointing at a row with a mouse picks it too, as on
  the board.
-->
<script lang="ts">
  import { explorerModel, explorerStep, EXPLORER_CHART } from '@syn137/skyline-core/patterns'
  import { tick } from 'svelte'
  import type { EvalExplorerProps } from './types'

  let {
    verifiers,
    passAt,
    judge,
    selected = $bindable(),
    span,
    ticks = [],
    costMax,
    onselect,
    ...rest
  }: EvalExplorerProps = $props()

  const m = $derived(explorerModel({ verifiers, passAt, judge, selected, span, costMax }))
  // The picked line draws last, on top of the others.
  const order = (lines: typeof m.quality) => [...lines.filter((l) => l.index !== m.selected), ...lines.filter((l) => l.index === m.selected)]
  const uid = $props.id()
  let group: HTMLDivElement | undefined = $state()

  function pick(index: number) {
    if (index === m.selected) return
    selected = index
    onselect?.(index)
  }

  async function onkey(e: KeyboardEvent) {
    const rows = m.rows
    let next: number | null = null
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') next = explorerStep(rows, m.selected, 1)
    else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') next = explorerStep(rows, m.selected, -1)
    else if (e.key === 'Home') next = rows[0]?.index ?? null
    else if (e.key === 'End') next = rows[rows.length - 1]?.index ?? null
    if (next === null) return
    e.preventDefault()
    pick(next)
    await tick()
    group?.querySelector<HTMLButtonElement>(`[data-index="${next}"]`)?.focus()
  }
</script>

<div {...rest} class="sky-explorer">
  <div class="sky-explorer__inner">
    <div class="sky-explorer__charts" part="charts">
      <span class="sky-explorer__caption">
        <span><strong>Quality score</strong> · 0 to 100, from the judge</span>
        {#if judge}<span class="sky-explorer__judge">judge: {judge}</span>{/if}
      </span>
      <div class="sky-explorer__chart" data-chart="quality">
        <svg viewBox="0 0 {EXPLORER_CHART.width} {EXPLORER_CHART.quality}" preserveAspectRatio="none" role="img" aria-label={m.summary}>
          {#each m.qualityGrid as y, i (i)}
            <line class="sky-explorer__grid" data-base={i === m.qualityGrid.length - 1} x1="0" x2={EXPLORER_CHART.width} y1={y} y2={y} />
          {/each}
          <line class="sky-explorer__pass" x1="0" x2={EXPLORER_CHART.width} y1={m.pass.y} y2={m.pass.y} />
          {#each order(m.quality) as l (l.index)}
            <path class="sky-explorer__line" data-on={l.index === m.selected} d={l.d} style:stroke={`var(${l.token})`} />
          {/each}
        </svg>
        <span class="sky-explorer__pass-label" style:top={`${m.pass.top * 100}%`} aria-hidden="true">{m.pass.label}</span>
      </div>
      <span class="sky-explorer__caption sky-explorer__caption--cost"><span><strong>Cost</strong> · per run</span></span>
      <div class="sky-explorer__chart" data-chart="cost">
        <svg viewBox="0 0 {EXPLORER_CHART.width} {EXPLORER_CHART.cost}" preserveAspectRatio="none" aria-hidden="true">
          {#each m.costGrid as y, i (i)}
            <line class="sky-explorer__grid" data-base={i === m.costGrid.length - 1} x1="0" x2={EXPLORER_CHART.width} y1={y} y2={y} />
          {/each}
          {#each order(m.cost) as l (l.index)}
            <path class="sky-explorer__line" data-on={l.index === m.selected} d={l.d} style:stroke={`var(${l.token})`} />
          {/each}
        </svg>
      </div>
      {#if ticks.length}
        <span class="sky-explorer__ticks" aria-hidden="true">{#each ticks as t, i (i)}<span>{t}</span>{/each}</span>
      {/if}
    </div>

    <div class="sky-explorer__board" part="ranking">
      <span class="sky-explorer__eyebrow" id="{uid}-rank">Ranked by quality per dollar</span>
      <div class="sky-explorer__rows" role="radiogroup" aria-labelledby="{uid}-rank" tabindex="-1" bind:this={group} onkeydown={onkey}>
        {#each m.rows as r (r.index)}
          {@const on = r.index === m.selected}
          <button
            type="button"
            class="sky-explorer__row"
            role="radio"
            aria-checked={on}
            tabindex={on ? 0 : -1}
            data-index={r.index}
            style:--_series={`var(${r.token})`}
            onclick={() => pick(r.index)}
            onpointerenter={(e) => {
              if (e.pointerType === 'mouse') pick(r.index)
            }}
          >
            <span class="sky-explorer__rank">{r.rank}</span>
            <span class="sky-explorer__who">
              <span class="sky-explorer__name"><span class="sky-explorer__key" aria-hidden="true"></span><span class="sky-explorer__model">{r.name}</span></span>
              {#if r.bestText}<span class="sky-explorer__best">{r.bestText}</span>{/if}
            </span>
            <span class="sky-explorer__nums">
              <span class="sky-explorer__score-col"><span class="sky-explorer__score">{r.score}</span><span class="sky-explorer__cost">{r.cost}/run</span></span>
              <span class="sky-explorer__word" data-tone={r.tone}>{r.word}</span>
            </span>
          </button>
        {/each}
      </div>
      {#if m.verdict}
        <div class="sky-explorer__readout" part="verdict" aria-live="polite">
          <span class="sky-explorer__headline"><span class="sky-explorer__big">{m.verdict.score}</span><span class="sky-explorer__sub">{m.readout}</span></span>
          <span class="sky-explorer__line-text">{m.verdict.line}</span>
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .sky-explorer {
    container-type: inline-size;
    min-width: 0;
  }
  .sky-explorer__inner {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 1.125rem;
  }
  @container (min-width: 50rem) {
    .sky-explorer__inner {
      grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr);
      gap: var(--ds-space-7);
    }
  }
  .sky-explorer__charts,
  .sky-explorer__board {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }
  .sky-explorer__caption {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-explorer__caption strong {
    font-weight: var(--ds-font-weight-semibold);
    color: var(--ds-color-fg);
  }
  .sky-explorer__caption--cost {
    margin-top: 14px;
  }
  .sky-explorer__judge {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    overflow-wrap: anywhere;
  }
  .sky-explorer__chart {
    position: relative;
  }
  .sky-explorer__chart[data-chart='quality'] {
    height: 10.375rem;
  }
  .sky-explorer__chart[data-chart='cost'] {
    height: 5.375rem;
  }
  @container (min-width: 50rem) {
    .sky-explorer__chart[data-chart='quality'] {
      height: 14.375rem;
    }
    .sky-explorer__chart[data-chart='cost'] {
      height: 7.5rem;
    }
  }
  .sky-explorer__chart svg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    overflow: visible;
  }
  .sky-explorer__grid {
    stroke: var(--sky-color-divider);
    vector-effect: non-scaling-stroke;
  }
  .sky-explorer__grid[data-base='true'] {
    stroke: var(--sky-color-border-strong);
  }
  .sky-explorer__pass {
    stroke: color-mix(in oklab, var(--ds-color-accent) 55%, var(--sky-color-border-strong));
    stroke-dasharray: 5 5;
    vector-effect: non-scaling-stroke;
  }
  .sky-explorer__pass-label {
    position: absolute;
    left: 6px;
    transform: translateY(-120%);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    color: color-mix(in oklab, var(--ds-color-accent) 45%, var(--sky-color-display-hi));
  }
  .sky-explorer__line {
    fill: none;
    stroke-width: 1.75;
    stroke-opacity: 0.22;
    stroke-linecap: round;
    stroke-linejoin: round;
    vector-effect: non-scaling-stroke;
    transition:
      stroke-opacity var(--sky-duration-base) var(--sky-ease-out),
      stroke-width var(--sky-duration-base) var(--sky-ease-out);
  }
  .sky-explorer__line[data-on='true'] {
    stroke-width: 3;
    stroke-opacity: 1;
  }
  .sky-explorer__ticks {
    display: flex;
    justify-content: space-between;
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-subtle);
  }
  .sky-explorer__eyebrow {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  .sky-explorer__rows {
    display: flex;
    flex-direction: column;
    gap: 6px;
    outline: none;
  }
  .sky-explorer__row {
    display: grid;
    grid-template-columns: 18px minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--ds-space-1) var(--ds-space-3);
    width: 100%;
    padding: var(--ds-space-3);
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) solid transparent;
    background: transparent;
    color: var(--ds-color-fg);
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition:
      background-color var(--sky-duration-base) var(--sky-ease-out),
      border-color var(--sky-duration-base) var(--sky-ease-out);
  }
  .sky-explorer__row[aria-checked='true'] {
    border-color: color-mix(in oklab, var(--_series) 55%, var(--ds-color-border));
    background: var(--ds-color-overlay);
  }
  .sky-explorer__row:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-explorer__row {
      min-height: var(--sky-size-touch);
    }
  }
  .sky-explorer__rank {
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-subtle);
  }
  .sky-explorer__who {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .sky-explorer__name {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
    min-width: 0;
  }
  .sky-explorer__key {
    flex-shrink: 0;
    width: 14px;
    height: 3px;
    border-radius: 2px;
    background: var(--_series);
  }
  .sky-explorer__model {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-data);
    overflow-wrap: anywhere;
  }
  @container (min-width: 28rem) {
    .sky-explorer__model {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
  }
  .sky-explorer__best {
    font-size: var(--ds-text-xs);
    color: color-mix(in oklab, var(--ds-color-accent) 45%, var(--sky-color-display-hi));
  }
  .sky-explorer__nums {
    display: flex;
    flex-direction: column-reverse;
    align-items: flex-end;
    gap: var(--ds-space-1);
  }
  @container (min-width: 28rem) {
    .sky-explorer__nums {
      flex-direction: row;
      align-items: center;
      gap: var(--ds-space-3);
    }
  }
  .sky-explorer__score-col {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
  }
  .sky-explorer__score {
    font-size: 1.125rem;
    font-weight: var(--ds-font-weight-semibold);
    font-variant-numeric: tabular-nums;
  }
  .sky-explorer__cost {
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    color: var(--ds-color-text-subtle);
  }
  .sky-explorer__word {
    height: 1.375rem;
    padding: 0 9px;
    border-radius: var(--ds-radius-full);
    background: var(--sky-color-neutral-soft);
    color: var(--ds-color-text-muted);
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-semibold);
    line-height: 1.375rem;
    white-space: nowrap;
  }
  .sky-explorer__word[data-tone='good'] {
    background: var(--sky-color-success-soft);
    color: var(--sky-color-success-soft-fg);
  }
  .sky-explorer__word[data-tone='bad'] {
    background: var(--sky-color-danger-soft);
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-explorer__readout {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-top: 10px;
    padding: 14px;
    border-radius: var(--sky-radius-row);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
  }
  .sky-explorer__headline {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 4px 10px;
  }
  .sky-explorer__big {
    font-size: 2.125rem;
    font-weight: var(--ds-font-weight-semibold);
    letter-spacing: -0.03em;
    line-height: 1.1;
  }
  .sky-explorer__sub {
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-muted);
  }
  .sky-explorer__line-text {
    font-size: var(--ds-text-sm);
    line-height: 1.5;
    color: var(--ds-color-fg);
  }
</style>
