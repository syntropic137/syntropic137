<!--
  Skyline with Day Readout (Main and PhoneOverview boards): every day as an
  extruded bar, taller for more sessions (sqrt scale). Point at a bar, focus
  it, click it or step with the buttons or arrow keys; the readout follows.

  Wide containers show the full year with the readout docked over the
  future part of the chart and a leader line to the picked bar (beside the
  chart instead when bars would sit under it). Narrow containers show the
  last 16 weeks with a Year toggle and the readout as a card underneath.
  All geometry comes from layoutSkyline() in skyline-core.
-->
<script lang="ts">
  import { tick } from 'svelte'
  import {
    SKYLINE_WEEKS,
    SKYLINE_YEAR,
    dayFromMs,
    describeSkyline,
    hitStyle,
    layoutSkyline,
    recentWeeksRange,
    skylineLeadPath,
    yearRange,
    type SkylineDay,
  } from '@syn137/skyline-core/geometry'
  import { GLYPH } from '@syn137/skyline-core/patterns'
  import { dayStepper, stepperKey, stepperPosition, type DayStepperEvent } from '@syn137/skyline-core/state'
  import DayReadout from '../DayReadout/DayReadout.svelte'
  import Glyph from '../Glyph/Glyph.svelte'
  import type { SkylineProps } from './types'

  let {
    days,
    today = dayFromMs(Date.now()),
    year,
    years = [],
    onyearchange,
    selected = $bindable(null),
    onselect,
    runsHref,
    wideFrom = 720,
    ...rest
  }: SkylineProps = $props()

  let width = $state(0)
  let chartWidth = $state(0)
  let dockWidth = $state(0)
  let phoneView = $state<'weeks' | 'year'>('weeks')
  let chartBox: HTMLDivElement | undefined = $state()

  const shownYear = $derived(year ?? Number(today.slice(0, 4)))
  // Before the first measurement, assume desktop so a server or test render shows the year.
  const wide = $derived(width === 0 || width >= wideFrom)
  const mode = $derived(wide || phoneView === 'year' ? 'year' : 'weeks')
  const dims = $derived(mode === 'weeks' ? SKYLINE_WEEKS : SKYLINE_YEAR)
  const range = $derived(mode === 'weeks' ? recentWeeksRange(today) : yearRange(shownYear))
  const layout = $derived(layoutSkyline({ days, range, today, dims }))
  const bars = $derived(layout.bars)
  const current = $derived.by(() => {
    if (bars.length === 0) return null
    const i = selected ? bars.findIndex((b) => b.date === selected) : -1
    return i >= 0 ? i : bars.length - 1
  })
  const bar = $derived(current === null ? null : (bars[current] ?? null))
  const position = $derived(stepperPosition({ index: current, count: bars.length }))
  const rangeLabel = $derived(mode === 'weeks' ? 'the last 16 weeks' : String(shownYear))

  // Docked readout geometry (wide only), in viewBox units.
  const vb = $derived(dims.viewBox)
  const scale = $derived(chartWidth > 0 ? chartWidth / vb.width : 1)
  const dockGapPx = 8
  const overlapX = $derived(vb.x + (chartWidth - dockGapPx - (dockWidth || 244)) / scale)
  const overlap = $derived(wide && chartWidth > 0 && bars.every((b) => b.hit.x + b.hit.width < overlapX))
  const leadTarget = $derived(overlap ? overlapX : vb.x + vb.width)
  const lead = $derived(wide && bar ? skylineLeadPath(bar, leadTarget, dims) : null)

  async function send(event: DayStepperEvent, focus = false) {
    const next = dayStepper({ index: current, count: bars.length }, event)
    if (next.index === null) return
    const b = bars[next.index]
    if (!b) return
    if (b.date !== selected) {
      selected = b.date
      onselect?.(b.day)
    }
    if (focus) {
      await tick()
      chartBox?.querySelector<HTMLButtonElement>(`[data-date="${b.date}"]`)?.focus()
    }
  }

  function onkey(e: KeyboardEvent) {
    const ev = stepperKey(e.key)
    if (!ev) return
    e.preventDefault()
    void send(ev, true)
  }
</script>

<div {...rest} class="sky-skyline" data-wide={wide || undefined} bind:clientWidth={width}>
  <div class="sky-skyline__controls">
    <span class="sky-skyline__caption">
      {#if wide}
        Agent activity · every day of {shownYear}. Taller means more sessions. Point at a bar, or step through the active days.
      {:else}
        Agent activity · {mode === 'weeks' ? 'last 16 weeks' : shownYear}
      {/if}
    </span>
    <div class="sky-skyline__tools">
      {#if wide}
        <div class="sky-skyline__stepper" role="group" aria-label="Active day">
          <button class="sky-skyline__step" type="button" aria-label="Previous active day" disabled={!bars.length} onclick={() => send({ type: 'prev' })}>
            <Glyph d={GLYPH.chevronLeft} weight={1.75} />
          </button>
          <span class="sky-skyline__pos">{position}</span>
          <button class="sky-skyline__step" type="button" aria-label="Next active day" disabled={!bars.length} onclick={() => send({ type: 'next' })}>
            <Glyph d={GLYPH.chevronRight} weight={1.75} />
          </button>
        </div>
        {#if years.length > 1}
          <div class="sky-skyline__segmented" role="group" aria-label="Year">
            {#each years as y (y)}
              <button type="button" aria-pressed={y === shownYear} onclick={() => onyearchange?.(y)}>{y}</button>
            {/each}
          </div>
        {/if}
      {:else}
        <div class="sky-skyline__segmented" role="group" aria-label="Range" data-size="lg">
          <button type="button" aria-pressed={phoneView === 'weeks'} onclick={() => (phoneView = 'weeks')}>16w</button>
          <button type="button" aria-pressed={phoneView === 'year'} onclick={() => (phoneView = 'year')}>Year</button>
        </div>
      {/if}
    </div>
  </div>

  <div class="sky-skyline__stage" data-overlap={overlap || undefined}>
    <div class="sky-skyline__chart" bind:this={chartBox} bind:clientWidth={chartWidth}>
      <svg class="sky-skyline__svg" viewBox={layout.viewBox} role="img" aria-label={describeSkyline(layout, rangeLabel)}>
        <path class="sky-skyline__floor" d={layout.floor} />
        <path class="sky-skyline__future" d={layout.future} />
        {#each [6, 5, 4, 3, 2, 1, 0] as j (j)}
          {@const row = layout.rows[j]}
          {#if row}
            <path class="sky-skyline__side" d={row.side} />
            <path class="sky-skyline__front" d={row.front} />
            <path class="sky-skyline__top" d={row.top} />
          {/if}
        {/each}
        {#if bar}
          <g class="sky-skyline__picked">
            <path class="sky-skyline__picked-side" d={bar.paths.side} />
            <path class="sky-skyline__picked-front" d={bar.paths.front} />
            <path class="sky-skyline__picked-top" d={bar.paths.top} />
          </g>
          {#if lead}
            <path class="sky-skyline__lead" d={lead} />
            <circle class="sky-skyline__dot" cx={bar.anchor.x} cy={bar.anchor.y} r="2.5" />
          {/if}
        {/if}
        <g class="sky-skyline__months" aria-hidden="true">
          {#each layout.months as m (m.label + m.x)}
            <text x={m.x} y={m.y}>{m.label}</text>
          {/each}
        </g>
      </svg>
      <div class="sky-skyline__hits" role="group" aria-label="Active days">
        {#each bars as b (b.date)}
          {@const css = hitStyle(b.hit, dims)}
          <button
            class="sky-skyline__hit"
            type="button"
            data-date={b.date}
            aria-label={b.label}
            aria-pressed={b.index === current}
            tabindex={b.index === current ? 0 : -1}
            style:left={css.left}
            style:top={css.top}
            style:width={css.width}
            style:height={css.height}
            style:z-index={b.hit.z}
            onmouseenter={() => send({ type: 'pick', index: b.index })}
            onfocus={() => send({ type: 'pick', index: b.index })}
            onclick={() => send({ type: 'pick', index: b.index })}
            onkeydown={onkey}
          ></button>
        {/each}
      </div>
    </div>
    {#if wide}
      <div class="sky-skyline__dock" bind:clientWidth={dockWidth}>
        <DayReadout day={bar?.day ?? null} variant="dock" runsHref={bar && runsHref ? runsHref(bar.day) : undefined} />
      </div>
    {/if}
  </div>

  {#if !wide}
    <DayReadout
      day={bar?.day ?? null}
      variant="card"
      {position}
      onprev={() => send({ type: 'prev' })}
      onnext={() => send({ type: 'next' })}
      runsHref={bar && runsHref ? runsHref(bar.day) : undefined}
    />
  {/if}
</div>

<style>
  .sky-skyline {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-3);
    min-width: 0;
  }
  .sky-skyline__controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-3);
  }
  .sky-skyline__caption {
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-skyline__tools {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2-5) var(--ds-space-4);
  }
  .sky-skyline__stepper {
    display: flex;
    align-items: center;
    gap: var(--ds-space-2);
  }
  .sky-skyline__step {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 1.75rem;
    height: 1.75rem;
    padding: 0;
    border-radius: var(--ds-radius-sm);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--sky-color-control);
    color: var(--ds-color-fg);
    cursor: pointer;
  }
  .sky-skyline__step:hover:not(:disabled) {
    background: var(--sky-color-control-hover);
  }
  .sky-skyline__step:disabled {
    color: var(--ds-color-text-subtle);
    cursor: default;
  }
  .sky-skyline__pos {
    min-width: 8.25rem;
    text-align: center;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-skyline__segmented {
    display: flex;
    gap: 2px;
    padding: 2px;
    border-radius: var(--ds-radius-sm);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
  }
  .sky-skyline__segmented button {
    height: 1.5rem;
    padding: 0 var(--ds-space-2-5);
    border: 0;
    border-radius: 7px;
    background: transparent;
    color: var(--ds-color-text-muted);
    font: inherit;
    cursor: pointer;
  }
  .sky-skyline__segmented[data-size='lg'] {
    padding: 3px;
    border-radius: var(--sky-radius-control);
  }
  .sky-skyline__segmented[data-size='lg'] button {
    height: 1.875rem;
    border-radius: var(--ds-radius-sm);
  }
  .sky-skyline__segmented button[aria-pressed='true'] {
    background: var(--ds-color-overlay);
    color: var(--ds-color-fg);
  }
  .sky-skyline__step:focus-visible,
  .sky-skyline__segmented button:focus-visible,
  .sky-skyline__hit:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }

  .sky-skyline__stage {
    position: relative;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--ds-space-4);
  }
  .sky-skyline[data-wide] .sky-skyline__stage:not([data-overlap]) {
    grid-template-columns: minmax(0, 1fr) 15.25rem;
  }
  .sky-skyline__stage[data-overlap] .sky-skyline__dock {
    position: absolute;
    top: 0;
    right: 8px;
    z-index: var(--sky-z-nav);
    width: 15.25rem;
  }
  .sky-skyline__chart {
    position: relative;
    min-width: 0;
  }
  .sky-skyline__svg {
    display: block;
    width: 100%;
    height: auto;
    overflow: visible;
  }
  .sky-skyline__floor {
    fill: var(--sky-color-neutral-soft);
  }
  .sky-skyline__future {
    fill: var(--sky-color-track);
  }
  .sky-skyline__side {
    fill: var(--sky-face-side);
  }
  .sky-skyline__front {
    fill: var(--sky-face-front);
  }
  .sky-skyline__top {
    fill: var(--sky-face-top);
  }
  .sky-skyline__picked path {
    stroke: var(--ds-color-fg);
    stroke-width: 1;
    stroke-linejoin: round;
  }
  .sky-skyline__picked-side {
    fill: var(--ds-color-accent);
  }
  .sky-skyline__picked-front {
    fill: color-mix(in oklab, var(--ds-color-accent) 62%, var(--ds-color-fg));
  }
  .sky-skyline__picked-top {
    fill: var(--ds-color-fg);
  }
  .sky-skyline__lead {
    fill: none;
    stroke: var(--ds-color-fg);
    stroke-opacity: 0.5;
    stroke-width: 1;
    stroke-dasharray: 2 3;
  }
  .sky-skyline__dot {
    fill: var(--ds-color-fg);
  }
  .sky-skyline__months {
    font-family: var(--ds-font-mono);
    font-size: 10px;
    fill: var(--ds-color-text-subtle);
  }
  .sky-skyline__hits {
    position: absolute;
    inset: 0;
    pointer-events: none;
  }
  .sky-skyline__hit {
    position: absolute;
    padding: 0;
    border: 0;
    border-radius: var(--ds-radius-xs);
    background: transparent;
    cursor: pointer;
    pointer-events: auto;
  }
  @media (pointer: coarse) {
    .sky-skyline__step,
    .sky-skyline__segmented button {
      min-width: var(--sky-size-touch);
      min-height: var(--sky-size-touch);
    }
  }
</style>
