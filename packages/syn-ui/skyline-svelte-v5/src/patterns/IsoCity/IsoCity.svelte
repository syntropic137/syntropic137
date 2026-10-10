<!--
  Iso City (Overview "Right now" heatmap; Main and PhoneOverview boards):
  an isometric floor of days. Weeks come toward the viewer, weekdays recede
  (Mon in front). Height is sessions (sqrt), the tone tier says how busy
  (dim, mid, hot with a rim and bloom) or that most runs failed (coral).
  Today's tile is lit with a thin beam. Older weeks sink into the fog on the
  left (SVG mask).

  Only a window shows: 14 weeks wide, 8 narrow. It scrolls by months: the
  buttons ("One month back", "One month forward", "Now"), a horizontal
  wheel or trackpad swipe, a drag or touch swipe, and the arrow keys when
  the chart is focused. The week strip under it shows the whole history
  with the window lit; a click jumps to that week's month. Pointing at,
  focusing or tapping a block shows its day in the readout; stepping active
  days scrolls only when the day is out of view.

  Geometry and month maths live in skyline-core (layoutIsoCityFloor,
  windowRange, offsetShowing, isoCityStrip). Weeks outside the window are
  laid out one either side (more during a glide) and stay hidden at rest.
  The glide is a CSS transition on the floor group; with reduced motion
  the duration token is 0 and the window jumps. Nothing loops.
-->
<script lang="ts">
  import { tick } from 'svelte'
  import {
    ISO_CITY_DESKTOP,
    ISO_CITY_PHONE,
    addDays,
    dayFromMs,
    isoCityHistory,
    isoCityStrip,
    isoCityWeeks,
    isoRangeLabel,
    layoutIsoCityFloor,
    maxMonthOffset,
    offsetForWeek,
    offsetLabel,
    offsetShowing,
    weekIndexOf,
    weekStartAt,
    windowRange,
    type SkylineDay,
  } from '@syn137/skyline-core/geometry'
  import { GLYPH } from '@syn137/skyline-core/patterns'
  import { stepperPosition } from '@syn137/skyline-core/state'
  import DayReadout from '../DayReadout/DayReadout.svelte'
  import Glyph from '../Glyph/Glyph.svelte'
  import type { IsoCityProps } from './types'

  let {
    days,
    today = dayFromMs(Date.now()),
    history = 52,
    window: windowProp,
    offset = $bindable(0),
    selected = $bindable(null),
    onselect,
    onwindow,
    runsHref,
    wideFrom = 720,
    badge,
    ...rest
  }: IsoCityProps = $props()

  const uid = $props.id()
  let width = $state(0)
  let chartWidth = $state(0)
  let chartBox: HTMLDivElement | undefined = $state()

  // Before the first measurement, assume desktop so a server or test render shows the board.
  const wide = $derived(width === 0 || width >= wideFrom)
  const dims = $derived(wide ? ISO_CITY_DESKTOP : ISO_CITY_PHONE)
  const win = $derived(windowProp ?? dims.win)
  const hist = $derived(isoCityHistory(today, history))
  const weeks = $derived(isoCityWeeks(days, hist.start, hist.weeks))
  const maxOffset = $derived(maxMonthOffset(hist, win))
  const off = $derived(Math.min(maxOffset, Math.max(0, Math.floor(offset))))
  const range = $derived(windowRange(hist, win, off))

  // ---- motion: `shift` weeks of translation still to glide away; `pad` weeks laid out each side ----
  let shift = $state(0)
  let pad = $state(1)
  let gliding = $state(false)
  let dragging = $state(false)
  let shownFirst = $state<number | null>(null)

  const strip = $derived(isoCityStrip(weeks, range.first, win, dims.tickEvery))
  const rangeLabel = $derived(isoRangeLabel(weekStartAt(hist, range.first), minDay(addDays(weekStartAt(hist, range.last), 6), today)))

  const active = $derived(days.filter((d) => d.sessions > 0 && d.date <= today && d.date >= hist.start).sort((a, b) => (a.date < b.date ? -1 : 1)))
  const currentIndex = $derived.by(() => {
    if (active.length === 0) return null
    const i = selected ? active.findIndex((d) => d.date === selected) : -1
    return i >= 0 ? i : active.length - 1
  })
  const current = $derived(currentIndex === null ? null : (active[currentIndex] ?? null))
  const layout = $derived(layoutIsoCityFloor({ weeks, first: range.first, window: win, today, dims, pad, selected: current?.date ?? null }))
  const position = $derived(stepperPosition({ index: currentIndex, count: active.length }))
  const moving = $derived(gliding || dragging)
  const translate = $derived(`translate(${round(shift * dims.ax)}px, ${round(shift * dims.ay)}px)`)

  function minDay(a: string, b: string): string {
    return a < b ? a : b
  }
  function round(v: number): number {
    return Math.round(v * 100) / 100
  }
  function reducedMotion(): boolean {
    return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
  }

  // Glide from wherever the floor was to the new window whenever the window moves.
  $effect.pre(() => {
    const first = range.first
    const prev = shownFirst
    shownFirst = first
    if (prev === null || prev === first) return
    glideFrom(first - prev)
  })

  $effect(() => {
    onwindow?.({ start: weekStartAt(hist, Math.max(0, range.first - 1)), end: addDays(weekStartAt(hist, range.last), 6), first: range.first })
  })

  function glideFrom(delta: number) {
    const from = shift + delta
    if (reducedMotion() || from === 0) {
      shift = 0
      gliding = false
      pad = 1
      return
    }
    pad = Math.ceil(Math.abs(from)) + 1
    gliding = false
    shift = from
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        gliding = true
        shift = 0
      }),
    )
  }

  function onglideend() {
    gliding = false
    pad = 1
  }

  function setOffset(n: number) {
    offset = Math.min(maxOffset, Math.max(0, n))
  }

  function pick(d: SkylineDay) {
    if (d.date === selected) return
    selected = d.date
    onselect?.(d)
  }

  async function step(dir: 1 | -1, focus = false) {
    if (currentIndex === null) return
    const d = active[(currentIndex + dir + active.length) % active.length]
    if (!d) return
    pick(d)
    setOffset(offsetShowing(hist, win, weekIndexOf(hist, d.date), off))
    if (!focus) return
    await tick()
    chartBox?.querySelector<HTMLButtonElement>(`[data-date="${d.date}"]`)?.focus()
  }

  // ---- real input: drag or swipe, wheel or trackpad, keys ----
  let dragX: number | null = null
  let dragId: number | null = null
  const weekPx = $derived(chartWidth > 0 ? (dims.ax * chartWidth) / dims.vw : dims.ax)

  function ondown(e: PointerEvent) {
    if (e.button !== 0) return
    dragX = e.clientX
    dragId = e.pointerId
  }
  function onmove(e: PointerEvent) {
    if (dragX === null || e.pointerId !== dragId) return
    const weeksMoved = (e.clientX - dragX) / weekPx
    if (!dragging && Math.abs(e.clientX - dragX) < 6) return
    if (!dragging) (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    dragging = true
    gliding = false
    shift = weeksMoved
    pad = Math.ceil(Math.abs(weeksMoved)) + 1
  }
  function onup(e: PointerEvent) {
    if (e.pointerId !== dragId) return
    const moved = shift
    dragX = null
    dragId = null
    if (!dragging) return
    dragging = false
    // About 4.35 weeks to a month; a quarter of a month's drag is enough to step.
    const months = Math.round((moved / 4.35) * 1.6)
    const next = Math.min(maxOffset, Math.max(0, off + Math.sign(months) * Math.min(Math.abs(months), 12)))
    if (next === off) glideFrom(0)
    else setOffset(next)
  }

  let wheelAcc = 0
  function onwheel(e: WheelEvent) {
    const dx = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.shiftKey ? e.deltaY : 0
    if (dx === 0) return
    e.preventDefault()
    if (moving) return
    wheelAcc += dx
    if (Math.abs(wheelAcc) < 80) return
    setOffset(off + (wheelAcc > 0 ? -1 : 1))
    wheelAcc = 0
  }

  function onchartkey(e: KeyboardEvent) {
    const onBlock = (e.target as HTMLElement).dataset.date !== undefined
    const key = e.key
    if (onBlock && (key === 'ArrowLeft' || key === 'ArrowRight')) {
      e.preventDefault()
      void step(key === 'ArrowLeft' ? -1 : 1, true)
      return
    }
    const months = key === 'ArrowLeft' || key === 'PageUp' ? 1 : key === 'ArrowRight' || key === 'PageDown' ? -1 : 0
    if (months !== 0) {
      e.preventDefault()
      setOffset(off + months)
    } else if (key === 'End') {
      e.preventDefault()
      setOffset(0)
    } else if (key === 'Home') {
      e.preventDefault()
      setOffset(maxOffset)
    }
  }

  const pct = (v: number, of: number) => `${round((v / of) * 100)}%`
</script>

<div {...rest} class="sky-iso" data-wide={wide || undefined} bind:clientWidth={width}>
  <div class="sky-iso__head">
    <div class="sky-iso__caption">
      <span class="sky-iso__title">Agent activity · <span class="sky-iso__range">{rangeLabel}</span>{#if badge}<span class="sky-iso__badge">{badge}</span>{/if}</span>
      {#if wide}
        <span class="sky-iso__hint">One block per day. Taller is more sessions; the busiest days glow, coral means most runs failed. Older weeks sink into the fog. Scroll back to bring them forward.</span>
      {:else}
        <span class="sky-iso__hint">Swipe the city sideways to go back in time.</span>
      {/if}
    </div>
    {#if wide}
      <div class="sky-iso__tools">
        {@render scroller()}
        <div class="sky-iso__group" role="group" aria-label="Active day">
          <button class="sky-iso__icon" type="button" aria-label="Previous active day" disabled={!active.length} onclick={() => step(-1)}><Glyph d={GLYPH.chevronLeft} weight={1.75} /></button>
          <span class="sky-iso__pos">{position}</span>
          <button class="sky-iso__icon" type="button" aria-label="Next active day" disabled={!active.length} onclick={() => step(1)}><Glyph d={GLYPH.chevronRight} weight={1.75} /></button>
        </div>
      </div>
    {/if}
  </div>

  <div class="sky-iso__stage">
    <!-- Drag, swipe and wheel are conveniences; the buttons, the week strip and the arrow keys carry the same moves. -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
    <div
      class="sky-iso__chart"
      role="group"
      tabindex="0"
      aria-label="Activity city, {offsetLabel(off, win)}. Left and right arrows scroll a month; on a day, they step active days."
      data-moving={moving || undefined}
      data-dragging={dragging || undefined}
      bind:this={chartBox}
      bind:clientWidth={chartWidth}
      onpointerdown={ondown}
      onpointermove={onmove}
      onpointerup={onup}
      onpointercancel={onup}
      onwheel={onwheel}
      onkeydown={onchartkey}
    >
      <svg class="sky-iso__svg" viewBox={layout.viewBox} role="img" aria-label="Isometric activity city for {rangeLabel}. Each block is a day; older weeks fade to the left. Use the arrows or the week strip below to scroll back in time.">
        <defs>
          <linearGradient id="{uid}-fog-g" x1="0" y1="0" x2="1" y2="0">
            <stop class="sky-iso__fog-stop" offset="0" stop-opacity="0" />
            <stop class="sky-iso__fog-stop" offset="0.08" stop-opacity="0.06" />
            <stop class="sky-iso__fog-stop" offset="0.4" stop-opacity="1" />
          </linearGradient>
          <mask id="{uid}-fog" maskUnits="userSpaceOnUse" x="0" y="0" width={dims.vw} height={dims.vh}>
            <rect x="0" y="0" width={dims.vw} height={dims.vh} fill="url(#{uid}-fog-g)" />
          </mask>
          <radialGradient id="{uid}-pool" cx="0.62" cy="0.78" r="0.55">
            <stop class="sky-iso__pool-in" offset="0" />
            <stop class="sky-iso__pool-out" offset="1" />
          </radialGradient>
          <linearGradient id="{uid}-beam" x1="0" y1="0" x2="0" y2="1">
            <stop class="sky-iso__beam-top" offset="0" />
            <stop class="sky-iso__beam-foot" offset="1" />
          </linearGradient>
          <filter id="{uid}-bloom" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="6" /></filter>
        </defs>
        <rect x="0" y="0" width={dims.vw} height={dims.vh} fill="url(#{uid}-pool)" />
        <g mask="url(#{uid}-fog)">
          <g class="sky-iso__floor-group" data-gliding={gliding || undefined} style:transform={translate} ontransitionend={onglideend}>
            <path class="sky-iso__floor" d={layout.floor} />
            <path class="sky-iso__floor" data-edge d={layout.floorEdge} />
            <path class="sky-iso__future" d={layout.future} />
            <path class="sky-iso__future" data-edge d={layout.futureEdge} />
            {#if layout.today}<path class="sky-iso__today" d={layout.today.tile} />{/if}
            <g class="sky-iso__months" aria-hidden="true">
              {#each layout.months as m (m.key)}
                <text transform={m.transform} data-edge={!m.inWindow || undefined}>{m.text}</text>
              {/each}
            </g>
            {#each layout.rows as row (row.row)}
              {#each row.blocks as b (b.date)}
                <g class="sky-iso__block" data-tone={b.tone} data-edge={!b.inWindow || undefined}>
                  <path class="sky-iso__side" d={b.side} />
                  <path class="sky-iso__front" d={b.front} />
                  <path class="sky-iso__top" d={b.top} />
                </g>
              {/each}
            {/each}
            <path class="sky-iso__glow" data-tone="hot" d={layout.glowHot} filter="url(#{uid}-bloom)" />
            <path class="sky-iso__glow" data-tone="fail" d={layout.glowFail} filter="url(#{uid}-bloom)" />
          </g>
          <g class="sky-iso__weekdays" aria-hidden="true">
            {#each layout.weekdays as w (w.key)}
              <text transform={w.transform}>{w.text}</text>
            {/each}
          </g>
        </g>
        <g style:transform={translate} class="sky-iso__floor-group" data-gliding={gliding || undefined}>
          {#if layout.today}
            <rect x={layout.today.beam.x} y={layout.today.beam.y} width={layout.today.beam.width} height={layout.today.beam.height} rx="1.5" fill="url(#{uid}-beam)" />
          {/if}
          {#if layout.selected && !moving}
            <g class="sky-iso__sel">
              <path class="sky-iso__sel-side" d={layout.selected.side} />
              <path class="sky-iso__sel-front" d={layout.selected.front} />
              <path class="sky-iso__sel-top" d={layout.selected.top} />
            </g>
            {#if wide && layout.lead}
              <path class="sky-iso__lead" d={layout.lead} />
              <circle class="sky-iso__dot" cx={layout.selected.anchor[0]} cy={layout.selected.anchor[1]} r="2.5" />
            {/if}
          {/if}
        </g>
      </svg>
      <div class="sky-iso__hits" role="group" aria-label="Active days in view">
        {#each layout.blocks as b (b.date)}
          {#if b.inWindow}
            <button
              class="sky-iso__hit"
              type="button"
              data-date={b.date}
              aria-label={b.label}
              aria-pressed={b.date === current?.date}
              tabindex={b.date === current?.date ? 0 : -1}
              style:left={pct(b.hit.x, dims.vw)}
              style:top={pct(b.hit.y, dims.vh)}
              style:width={pct(b.hit.width, dims.vw)}
              style:height={pct(b.hit.height, dims.vh)}
              style:z-index={b.z}
              onpointerenter={(e) => e.pointerType === 'mouse' && pick(b.day)}
              onfocus={() => pick(b.day)}
              onclick={() => pick(b.day)}
            ></button>
          {/if}
        {/each}
      </div>
    </div>
    {#if wide}
      <div class="sky-iso__dock">
        <DayReadout day={current} variant="dock" runsHref={current && runsHref ? runsHref(current) : undefined} />
      </div>
    {/if}
  </div>

  {#if !wide}{@render scroller()}{/if}

  <div class="sky-iso__strip">
    <div class="sky-iso__bars" role="group" aria-label="Whole history, one bar per week. The lit window is the part shown above.">
      {#each strip.bars as m (m.start)}
        <button class="sky-iso__bar" type="button" aria-label={m.label} data-week={m.week} onclick={() => setOffset(offsetForWeek(hist, win, m.week))}>
          <span data-tone={m.tone} style:height={m.height ? `${m.height}%` : '2px'}></span>
        </button>
      {/each}
      <span class="sky-iso__window" aria-hidden="true" style:left="{strip.windowLeft}%" style:width="{strip.windowWidth}%"></span>
    </div>
    <div class="sky-iso__ticks" aria-hidden="true">
      {#each strip.ticks as k (k.left)}<span style:left="{k.left}%">{k.text}</span>{/each}
      <span class="sky-iso__now">Now</span>
    </div>
  </div>

  {#if !wide}
    <DayReadout day={current} variant="card" {position} onprev={() => step(-1)} onnext={() => step(1)} runsHref={current && runsHref ? runsHref(current) : undefined} />
  {/if}
</div>

{#snippet scroller()}
  <div class="sky-iso__group sky-iso__scroll" role="group" aria-label="Scroll through time">
    <button class="sky-iso__icon" type="button" aria-label="One month back" disabled={off >= maxOffset} onclick={() => setOffset(off + 1)}><Glyph d={GLYPH.chevronLeft} weight={1.75} /></button>
    <span class="sky-iso__back" aria-live="polite">{offsetLabel(off, win)}</span>
    <button class="sky-iso__icon" type="button" aria-label="One month forward" disabled={off <= 0} onclick={() => setOffset(off - 1)}><Glyph d={GLYPH.chevronRight} weight={1.75} /></button>
    <span class="sky-iso__sep" aria-hidden="true"></span>
    <button class="sky-iso__now-button" type="button" aria-pressed={off === 0} onclick={() => setOffset(0)}>Now</button>
  </div>
{/snippet}

<style>
  .sky-iso {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-4);
    min-width: 0;
    color: var(--ds-color-fg);
  }
  .sky-iso__head {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--ds-space-3) var(--ds-space-6);
  }
  .sky-iso__caption {
    display: flex;
    flex-direction: column;
    gap: 3px;
    max-width: 32.5rem;
  }
  .sky-iso__title {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-1-5) var(--ds-space-2);
    font-size: var(--ds-text-sm);
    color: var(--ds-color-text-muted);
  }
  .sky-iso__range {
    color: var(--ds-color-fg);
  }
  .sky-iso__badge {
    padding: 1px 7px;
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    font-family: var(--ds-font-mono);
    font-size: 0.625rem;
    color: var(--ds-color-text-subtle);
  }
  .sky-iso__hint {
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-subtle);
  }
  .sky-iso__tools {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2-5) var(--ds-space-4);
  }
  .sky-iso__group {
    display: flex;
    align-items: center;
    gap: 2px;
    padding: 3px;
    border-radius: var(--sky-radius-control);
    border: var(--ds-border-width) solid var(--ds-color-border);
    background: var(--ds-color-bg);
  }
  .sky-iso__icon,
  .sky-iso__now-button {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: var(--sky-size-touch);
    height: var(--sky-size-touch);
    padding: 0;
    border: 0;
    border-radius: 13px;
    background: transparent;
    color: var(--ds-color-text-muted);
    cursor: pointer;
  }
  .sky-iso__icon:hover:not(:disabled) {
    background: var(--sky-color-control-hover);
    color: var(--ds-color-fg);
  }
  .sky-iso__icon:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .sky-iso__now-button {
    width: auto;
    padding: 0 var(--ds-space-4);
    background: var(--sky-color-accent-soft);
    color: var(--sky-color-accent-soft-fg);
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    font-weight: var(--ds-font-weight-semibold);
  }
  .sky-iso__back {
    flex-grow: 1;
    padding: 0 var(--ds-space-1-5);
    text-align: center;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-fg);
  }
  .sky-iso__pos {
    min-width: 8.25rem;
    text-align: center;
    font-family: var(--ds-font-mono);
    font-size: var(--ds-text-xs);
    color: var(--ds-color-text-muted);
  }
  .sky-iso__sep {
    width: 1px;
    height: 18px;
    margin: 0 var(--ds-space-1);
    background: var(--sky-iso-future-edge);
  }
  .sky-iso[data-wide] .sky-iso__icon {
    width: 28px;
    height: 28px;
    border-radius: 9px;
  }
  .sky-iso[data-wide] .sky-iso__now-button {
    height: 28px;
    padding: 0 var(--ds-space-3);
    border-radius: 9px;
  }
  .sky-iso[data-wide] .sky-iso__back {
    flex-grow: 0;
    min-width: 7.25rem;
  }
  .sky-iso:not([data-wide]) .sky-iso__scroll {
    margin: 0 var(--ds-space-1);
    border-radius: var(--ds-space-4);
  }

  .sky-iso__stage {
    position: relative;
  }
  .sky-iso__chart {
    position: relative;
    touch-action: pan-y;
    user-select: none;
    border-radius: var(--sky-radius-xl);
  }
  .sky-iso__chart[data-dragging] {
    cursor: grabbing;
  }
  .sky-iso__chart:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-iso__svg {
    display: block;
    width: 100%;
    height: auto;
    overflow: visible;
  }
  .sky-iso__fog-stop {
    stop-color: var(--sky-color-display-hi);
  }
  .sky-iso__pool-in {
    stop-color: var(--sky-iso-pool);
  }
  .sky-iso__pool-out {
    stop-color: transparent;
  }
  .sky-iso__beam-top {
    stop-color: var(--ds-color-accent);
    stop-opacity: 0;
  }
  .sky-iso__beam-foot {
    stop-color: var(--sky-iso-beam);
    stop-opacity: 0.9;
  }
  .sky-iso__floor-group[data-gliding] {
    transition: transform var(--sky-duration-slow) var(--sky-ease-out);
  }
  .sky-iso__floor {
    fill: var(--sky-iso-floor);
    stroke: var(--sky-iso-floor-edge);
    stroke-width: 0.6;
  }
  .sky-iso__future {
    fill: none;
    stroke: var(--sky-iso-future-edge);
    stroke-width: 0.6;
    stroke-dasharray: 2 2;
  }
  .sky-iso__today {
    fill: var(--sky-iso-today);
    stroke: var(--sky-iso-today-edge);
    stroke-width: 1.2;
    stroke-linejoin: round;
  }
  .sky-iso__months text,
  .sky-iso__weekdays text {
    font-family: var(--ds-font-mono);
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .sky-iso__months text {
    font-size: 10px;
    fill: var(--sky-iso-label);
  }
  .sky-iso__weekdays text {
    font-size: 9px;
    fill: var(--sky-iso-label-faint);
  }
  .sky-iso [data-edge] {
    opacity: 0;
  }
  .sky-iso__chart[data-moving] [data-edge] {
    opacity: 1;
  }
  .sky-iso__front {
    stroke: var(--sky-iso-face-edge);
    stroke-width: 0.5;
  }
  .sky-iso__top {
    stroke-width: 0.6;
    stroke-linejoin: round;
  }
  .sky-iso__block[data-tone='dim'] .sky-iso__side {
    fill: var(--sky-iso-dim-side);
  }
  .sky-iso__block[data-tone='dim'] .sky-iso__front {
    fill: var(--sky-iso-dim-front);
  }
  .sky-iso__block[data-tone='dim'] .sky-iso__top {
    fill: var(--sky-iso-dim-top);
    stroke: var(--sky-iso-dim-rim);
  }
  .sky-iso__block[data-tone='mid'] .sky-iso__side {
    fill: var(--sky-iso-mid-side);
  }
  .sky-iso__block[data-tone='mid'] .sky-iso__front {
    fill: var(--sky-iso-mid-front);
  }
  .sky-iso__block[data-tone='mid'] .sky-iso__top {
    fill: var(--sky-iso-mid-top);
    stroke: var(--sky-iso-mid-rim);
    stroke-opacity: 0.55;
  }
  .sky-iso__block[data-tone='hot'] .sky-iso__side {
    fill: var(--sky-iso-hot-side);
  }
  .sky-iso__block[data-tone='hot'] .sky-iso__front {
    fill: var(--sky-iso-hot-front);
  }
  .sky-iso__block[data-tone='hot'] .sky-iso__top {
    fill: var(--sky-iso-hot-top);
    stroke: var(--sky-iso-hot-rim);
    stroke-opacity: 0.7;
    stroke-width: 0.7;
  }
  .sky-iso__block[data-tone='fail'] .sky-iso__side {
    fill: var(--sky-iso-fail-side);
  }
  .sky-iso__block[data-tone='fail'] .sky-iso__front {
    fill: var(--sky-iso-fail-front);
  }
  .sky-iso__block[data-tone='fail'] .sky-iso__top {
    fill: var(--sky-iso-fail-top);
    stroke: var(--sky-iso-fail-rim);
    stroke-opacity: 0.7;
    stroke-width: 0.7;
  }
  .sky-iso__glow {
    mix-blend-mode: screen;
    pointer-events: none;
  }
  .sky-iso__glow[data-tone='hot'] {
    fill: var(--ds-color-accent);
    opacity: 0.55;
  }
  .sky-iso__glow[data-tone='fail'] {
    fill: var(--ds-color-danger);
    opacity: 0.5;
  }
  .sky-iso__sel path {
    stroke: var(--sky-color-display-hi);
    stroke-width: 1;
    stroke-linejoin: round;
  }
  .sky-iso__sel-side {
    fill: var(--sky-iso-sel-side);
  }
  .sky-iso__sel-front {
    fill: var(--sky-iso-sel-front);
  }
  .sky-iso__sel-top {
    fill: var(--sky-color-display-hi);
  }
  .sky-iso__lead {
    fill: none;
    stroke: var(--sky-color-display-hi);
    stroke-opacity: 0.45;
    stroke-width: 1;
    stroke-dasharray: 2 3;
  }
  .sky-iso__dot {
    fill: var(--sky-color-display-hi);
  }
  .sky-iso__hits {
    position: absolute;
    inset: 0;
  }
  .sky-iso__chart[data-moving] .sky-iso__hits {
    pointer-events: none;
  }
  .sky-iso__hit {
    position: absolute;
    padding: 0;
    border: 0;
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
  }
  .sky-iso__hit:focus-visible,
  .sky-iso__icon:focus-visible,
  .sky-iso__now-button:focus-visible,
  .sky-iso__bar:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-iso__dock {
    margin-top: var(--ds-space-3);
  }
  .sky-iso[data-wide] .sky-iso__dock {
    position: absolute;
    top: 0;
    right: var(--ds-space-2);
    z-index: 20;
    width: 15.25rem;
    margin: 0;
  }

  .sky-iso__strip {
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-2);
    padding: var(--ds-space-1-5) var(--ds-space-2) 0;
  }
  .sky-iso[data-wide] .sky-iso__strip {
    padding: var(--ds-space-4) var(--ds-space-4) 0;
  }
  .sky-iso__bars {
    position: relative;
    display: flex;
    align-items: flex-end;
    height: 26px;
    border-bottom: var(--ds-border-width) solid var(--sky-iso-future-edge);
  }
  .sky-iso__bar {
    display: flex;
    align-items: flex-end;
    flex: 1 1 0;
    min-width: 0;
    height: 100%;
    padding: 0 1px;
    border: 0;
    background: transparent;
    cursor: pointer;
  }
  .sky-iso__bar span {
    display: block;
    width: 100%;
    border-radius: 1px 1px 0 0;
    background: var(--sky-iso-strip-dim);
  }
  .sky-iso__bar span[data-tone='lit'] {
    background: var(--sky-iso-strip-lit);
  }
  .sky-iso__bar span[data-tone='fail'] {
    background: var(--ds-color-danger);
  }
  .sky-iso__window {
    position: absolute;
    top: -6px;
    bottom: -1px;
    box-sizing: border-box;
    border-top: 2px solid var(--ds-color-accent);
    border-radius: 2px;
    background: linear-gradient(180deg, var(--sky-color-accent-soft), transparent 85%);
    pointer-events: none;
  }
  .sky-iso__ticks {
    position: relative;
    height: 12px;
    font-family: var(--ds-font-mono);
    font-size: 0.59375rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--sky-iso-label);
  }
  .sky-iso__ticks span {
    position: absolute;
    top: 0;
  }
  .sky-iso__ticks .sky-iso__now {
    right: 0;
    color: var(--sky-iso-now);
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-iso__window {
      transition: left var(--sky-duration-slow) var(--sky-ease-out);
    }
  }
</style>
