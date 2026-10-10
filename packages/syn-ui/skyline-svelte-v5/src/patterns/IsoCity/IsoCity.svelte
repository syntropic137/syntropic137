<!--
  Iso City (Overview "Right now" heatmap; Main and PhoneOverview boards):
  an isometric floor of days. Weeks come toward the viewer, and so do the
  days of a week: Monday at the back, Sunday in front (owner, Oct 10), so
  today is never hidden behind a later day. Height is sessions (sqrt), the
  tone tier says how busy (dim, mid, hot with a rim and bloom) or that most
  runs failed (coral). Today's tile is lit with a thin beam; the rest of
  today's week is future tiles, so every week is a full column. Older weeks
  sink into the fog on the left (SVG mask).

  Only a window shows: as many weeks as fit the board's own column on the
  desktop board (measured with a ResizeObserver, a cell of gutter each
  side), 8 narrow, centred. From 64rem the readout is a grid column beside
  the board, never over it, so today is never hidden. It scrolls by
  months: the buttons ("One month back", "One month forward", "Now"), a
  horizontal wheel or trackpad swipe, a drag or touch swipe, and the arrow
  keys when the chart is focused. The week strip under it shows the whole
  history with the window lit; a click jumps to that week's month. Pointing
  at a block picks the day whose painted surface is on top (visible-surface
  picking); focusing or tapping a day shows it in the readout. One visible
  day is always the Tab stop (roving focus), apart from the selection.

  Motion (owner, Oct 10): a scroll is one continuous glide. The floor stays
  laid out around the window it last landed on and translates by the whole
  delta in one CSS transition; the window moves to the target only when the
  glide lands, so nothing re-paints mid-glide. Wheel steps and button
  presses mid-glide retarget the same transition. Blocks leaving the target
  window fade and drop, blocks entering fade and rise, and an edge mask
  along the week axis fades whole columns at both edges. Reduced motion:
  one crossfade, no translation. The only timer is the landing backstop,
  cleared on every retarget and on unmount.

  Geometry, picking, keys and the glide live in skyline-core
  (layoutIsoCityFloor, pickIsoCityBlock, isoCityKeyIntent, isoGlide).
-->
<script lang="ts">
  import { tick, untrack } from 'svelte'
  import {
    ISO_CITY_DESKTOP,
    ISO_CITY_PHONE,
    addDays,
    dayFromMs,
    isoCityCentred,
    isoCityEdgeMask,
    isoCityFit,
    isoCityHistory,
    isoCityKeyIntent,
    isoCityRovingDate,
    isoCityStrip,
    isoCityWeeks,
    isoRangeLabel,
    layoutIsoCityFloor,
    maxMonthOffset,
    offsetForWeek,
    offsetLabel,
    offsetShowing,
    pickIsoCityBlock,
    toViewBox,
    weekIndexOf,
    weekStartAt,
    windowRange,
    type IsoCityBlock,
    type SkylineDay,
  } from '@syn137/skyline-core/geometry'
  import { GLYPH } from '@syn137/skyline-core/patterns'
  import { glideFocusFirst, initialIsoGlide, isoGlide, stepperPosition, type IsoGlideEvent } from '@syn137/skyline-core/state'
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
    coverage = null,
    onretry,
    ...rest
  }: IsoCityProps = $props()

  /** Landing backstop: the glide's CSS duration (--sky-duration-slow, 360ms) plus slack, in case transitionend never comes. */
  const LAND_BACKSTOP_MS = 520

  const uid = $props.id()
  let width = $state(0)
  let chartWidth = $state(0)
  let chartBox: HTMLDivElement | undefined = $state()

  // Before the first measurement, assume desktop so a server or test render shows the board.
  const wide = $derived(width === 0 || width >= wideFrom)
  // Desktop: the board is fitted to its own column (one unit per CSS pixel); phone: the board as drawn.
  const dims = $derived(wide ? isoCityFit(ISO_CITY_DESKTOP, chartWidth, windowProp) : isoCityCentred(ISO_CITY_PHONE, windowProp ?? ISO_CITY_PHONE.win))
  const win = $derived(dims.win)
  const edge = $derived(isoCityEdgeMask(dims, win))
  const hist = $derived(isoCityHistory(today, history))
  const weeks = $derived(isoCityWeeks(days, hist.start, hist.weeks))
  const maxOffset = $derived(maxMonthOffset(hist, win))
  const off = $derived(Math.min(maxOffset, Math.max(0, Math.floor(offset))))
  const range = $derived(windowRange(hist, win, off))

  // ---- motion: the floor is laid out around glide.anchor and translated by glide.shift weeks ----
  let glide = $state(initialIsoGlide)
  let fadeTick = $state(0)
  const send = (e: IsoGlideEvent) => (glide = isoGlide(glide, e))
  const anchor = $derived(glide.anchor ?? range.first)
  const focusFirst = $derived(glideFocusFirst(glide, range.first))
  const moving = $derived(glide.gliding || glide.dragging)

  const strip = $derived(isoCityStrip(weeks, range.first, win, dims.tickEvery, coverage))
  const rangeLabel = $derived(isoRangeLabel(weekStartAt(hist, range.first), minDay(addDays(weekStartAt(hist, range.last), 6), today)))
  // Nothing loaded yet: every past day is unknown.
  const loadedFrom = $derived(coverage ? (coverage.from ?? addDays(today, 1)) : null)

  const active = $derived(days.filter((d) => d.sessions > 0 && d.date <= today && d.date >= hist.start).sort((a, b) => (a.date < b.date ? -1 : 1)))
  const currentIndex = $derived.by(() => {
    if (active.length === 0) return null
    const i = selected ? active.findIndex((d) => d.date === selected) : -1
    return i >= 0 ? i : active.length - 1
  })
  const current = $derived(currentIndex === null ? null : (active[currentIndex] ?? null))
  const layout = $derived(layoutIsoCityFloor({ weeks, first: anchor, window: win, today, dims, pad: glide.pad, selected: current?.date ?? null, loadedFrom }))
  const position = $derived(stepperPosition({ index: currentIndex, count: active.length }))
  const translate = $derived(`translate(${round(glide.shift * dims.ax)}px, ${round(glide.shift * dims.ay)}px)`)
  // The hit layer is HTML over the SVG: the same translation in CSS pixels.
  const scale = $derived(chartWidth > 0 ? chartWidth / dims.vw : 1)
  const hitTranslate = $derived(`translate(${round(glide.shift * dims.ax * scale)}px, ${round(glide.shift * dims.ay * scale)}px)`)

  const inFocus = (b: IsoCityBlock) => b.week >= focusFirst && b.week < focusFirst + win
  /** Day buttons: the days of the window the glide is heading for. Buffer weeks are never focusable. */
  const dayButtons = $derived(layout.blocks.filter(inFocus))
  const roving = $derived(isoCityRovingDate(dayButtons.map((b) => b.date), current?.date))

  function minDay(a: string, b: string): string {
    return a < b ? a : b
  }
  function round(v: number): number {
    return Math.round(v * 100) / 100
  }
  function reducedMotion(): boolean {
    return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
  }

  // The board column's width, from a ResizeObserver on the column itself (not the window).
  $effect(() => {
    const el = chartBox
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0
      if (w > 0 && Math.abs(w - chartWidth) >= 1) chartWidth = w
    })
    ro.observe(el)
    return () => ro.disconnect()
  })

  // The window moved: glide there (or retarget the glide in flight).
  let lastWin = 0
  $effect.pre(() => {
    const first = range.first
    const w = win
    untrack(() => {
      // A resize that changes the week count re-frames at once; only scrolling glides.
      const resized = lastWin !== 0 && w !== lastWin
      lastWin = w
      const reduced = reducedMotion() || resized
      const was = glide.anchor
      send({ type: 'target', first, reduced })
      if (reduced && !resized && was !== null && was !== first) fadeTick++
    })
  })

  // Landing backstop, re-armed by every retarget and cleared on unmount.
  $effect(() => {
    if (!glide.gliding) return
    void glide.shift
    const id = setTimeout(land, LAND_BACKSTOP_MS)
    return () => clearTimeout(id)
  })

  $effect(() => {
    onwindow?.({ start: weekStartAt(hist, Math.max(0, range.first - 1)), end: addDays(weekStartAt(hist, range.last), 6), first: range.first })
  })

  function land() {
    if (glide.gliding) send({ type: 'land', first: range.first })
  }

  function onglideend(e: TransitionEvent) {
    if (e.target !== e.currentTarget) return
    if (e.propertyName && e.propertyName !== 'transform') return
    land()
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

  // ---- pointing: the block painted on top under the pointer ----
  function blockAt(e: MouseEvent): IsoCityBlock | null {
    if (!chartBox || moving) return null
    const p = toViewBox(e.clientX, e.clientY, chartBox.getBoundingClientRect(), dims.vw, dims.vh)
    return p ? pickIsoCityBlock(dayButtons, p[0], p[1]) : null
  }

  // ---- real input: drag or swipe, wheel or trackpad, keys ----
  let dragX: number | null = null
  let dragId: number | null = null
  let dragged = false
  const weekPx = $derived(chartWidth > 0 ? (dims.ax * chartWidth) / dims.vw : dims.ax)

  function ondown(e: PointerEvent) {
    if (e.button !== 0) return
    dragX = e.clientX
    dragId = e.pointerId
    dragged = false
  }
  function onmove(e: PointerEvent) {
    if (dragX === null || e.pointerId !== dragId) {
      if (e.pointerType === 'mouse') hover(e)
      return
    }
    if (!glide.dragging && Math.abs(e.clientX - dragX) < 6) return
    if (!glide.dragging) (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    dragged = true
    send({ type: 'drag', weeks: (e.clientX - dragX) / weekPx, first: range.first })
  }
  function hover(e: PointerEvent) {
    const b = blockAt(e)
    if (b) pick(b.day)
  }
  function onup(e: PointerEvent) {
    if (e.pointerId !== dragId) return
    dragX = null
    dragId = null
    if (!glide.dragging) return
    const moved = glide.shift
    // About 4.35 weeks to a month; a quarter of a month's drag is enough to step.
    const months = Math.round((moved / 4.35) * 1.6)
    send({ type: 'release' })
    setOffset(off + Math.sign(months) * Math.min(Math.abs(months), 12))
  }
  function onchartclick(e: MouseEvent) {
    // detail 0 is a keyboard activation of a day button: that button already picked its day.
    if (e.detail === 0 || dragged) return
    const b = blockAt(e)
    if (b) pick(b.day)
  }

  let wheelAcc = 0
  function onwheel(e: WheelEvent) {
    const dx = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.shiftKey ? e.deltaY : 0
    if (dx === 0) return
    e.preventDefault()
    if (glide.dragging) return
    // Steps accumulate into the glide in flight (it retargets) rather than waiting for it.
    wheelAcc += dx
    if (Math.abs(wheelAcc) < 80) return
    setOffset(off + (wheelAcc > 0 ? -1 : 1))
    wheelAcc = 0
  }

  function onchartkey(e: KeyboardEvent) {
    const intent = isoCityKeyIntent(e.key, { onDay: (e.target as HTMLElement).dataset.date !== undefined, offset: off, maxOffset })
    if (!intent) return
    e.preventDefault()
    if (intent.kind === 'step') void step(intent.dir, true)
    else setOffset(intent.offset)
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

  <div class="sky-iso__stage" data-wide={wide || undefined}>
    <!-- Drag, swipe, wheel and pointing are conveniences; the buttons, the week strip, the day buttons and the arrow keys carry the same moves. -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions, a11y_click_events_have_key_events -->
    <div
      class="sky-iso__chart"
      role="group"
      tabindex="0"
      aria-label="Activity city, {offsetLabel(off, win)}. Left and right arrows scroll a month; on a day, they step active days."
      data-moving={moving || undefined}
      data-dragging={glide.dragging || undefined}
      data-anchor={anchor}
      bind:this={chartBox}
      onpointerdown={ondown}
      onpointermove={onmove}
      onpointerup={onup}
      onpointercancel={onup}
      onclick={onchartclick}
      onwheel={onwheel}
      onkeydown={onchartkey}
    >
      <svg class="sky-iso__svg" viewBox={layout.viewBox} role="img" data-fade={fadeTick === 0 ? undefined : fadeTick % 2 ? 'a' : 'b'} aria-label="Isometric activity city for {rangeLabel}. Each block is a day; older weeks fade to the left. Use the arrows or the week strip below to scroll back in time.">
        <defs>
          <linearGradient id="{uid}-fog-g" x1="0" y1="0" x2="1" y2="0">
            <stop class="sky-iso__fog-stop" offset="0" stop-opacity="0" />
            <stop class="sky-iso__fog-stop" offset="0.08" stop-opacity="0.06" />
            <stop class="sky-iso__fog-stop" offset="0.4" stop-opacity="1" />
          </linearGradient>
          <mask id="{uid}-fog" maskUnits="userSpaceOnUse" x="0" y="0" width={dims.vw} height={dims.vh}>
            <rect x="0" y="0" width={dims.vw} height={dims.vh} fill="url(#{uid}-fog-g)" />
          </mask>
          <linearGradient id="{uid}-edge-g" gradientUnits="userSpaceOnUse" x1={edge.x1} y1={edge.y1} x2={edge.x2} y2={edge.y2}>
            {#each edge.stops as s, i (i)}<stop class="sky-iso__fog-stop" offset={s.offset} stop-opacity={s.opacity} />{/each}
          </linearGradient>
          <mask id="{uid}-edge" maskUnits="userSpaceOnUse" x="0" y="0" width={dims.vw} height={dims.vh}>
            <rect x="0" y="0" width={dims.vw} height={dims.vh} fill="url(#{uid}-edge-g)" />
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
        <g mask="url(#{uid}-edge)">
          <g mask="url(#{uid}-fog)">
            <g class="sky-iso__floor-group" data-gliding={glide.gliding || undefined} style:transform={translate} ontransitionend={onglideend}>
              <path class="sky-iso__floor" d={layout.floor} />
              <path class="sky-iso__floor" data-edge d={layout.floorEdge} />
              <path class="sky-iso__unloaded" d={layout.unloaded} />
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
                  <g class="sky-iso__block" data-tone={b.tone} data-out={!inFocus(b) || undefined} data-date-block={b.date}>
                    <path class="sky-iso__side" d={b.side} />
                    <path class="sky-iso__front" d={b.front} />
                    <path class="sky-iso__top" d={b.top} />
                  </g>
                {/each}
              {/each}
              <path class="sky-iso__glow" data-tone="hot" d={layout.glowHot} filter="url(#{uid}-bloom)" />
              <path class="sky-iso__glow" data-tone="fail" d={layout.glowFail} filter="url(#{uid}-bloom)" />
            </g>
          </g>
          <g style:transform={translate} class="sky-iso__floor-group" data-gliding={glide.gliding || undefined}>
            {#if layout.today}
              <rect x={layout.today.beam.x} y={layout.today.beam.y} width={layout.today.beam.width} height={layout.today.beam.height} rx="1.5" fill="url(#{uid}-beam)" />
            {/if}
            {#if layout.selected && !moving}
              <g class="sky-iso__sel">
                <path class="sky-iso__sel-side" d={layout.selected.side} />
                <path class="sky-iso__sel-front" d={layout.selected.front} />
                <path class="sky-iso__sel-top" d={layout.selected.top} />
              </g>
            {/if}
          </g>
        </g>
        {#if layout.selected && !moving && wide && layout.lead}
          <path class="sky-iso__lead" d={layout.lead} />
          <circle class="sky-iso__dot" cx={layout.selected.anchor[0]} cy={layout.selected.anchor[1]} r="2.5" />
        {/if}
        <g class="sky-iso__weekdays" aria-hidden="true">
          {#each layout.weekdays as w (w.key)}
            <text transform={w.transform}>{w.text}</text>
          {/each}
        </g>
      </svg>
      <div class="sky-iso__hits" role="group" aria-label="Active days in view" data-gliding={glide.gliding || undefined} style:transform={hitTranslate}>
        {#each dayButtons as b (b.date)}
          <button
            class="sky-iso__hit"
            type="button"
            data-date={b.date}
            aria-label={b.label}
            aria-pressed={b.date === current?.date}
            tabindex={b.date === roving ? 0 : -1}
            style:left={pct(b.hit.x, dims.vw)}
            style:top={pct(b.hit.y, dims.vh)}
            style:width={pct(b.hit.width, dims.vw)}
            style:height={pct(b.hit.height, dims.vh)}
            style:z-index={b.z}
            onfocus={() => pick(b.day)}
            onclick={() => pick(b.day)}
          ></button>
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
        <button class="sky-iso__bar" type="button" aria-label={m.label} data-week={m.week} data-status={m.status} onclick={() => setOffset(offsetForWeek(hist, win, m.week))}>
          <span data-tone={m.tone} style:height={m.height ? `${m.height}%` : '2px'}></span>
        </button>
      {/each}
      <span class="sky-iso__window" aria-hidden="true" style:left="{strip.windowLeft}%" style:width="{strip.windowWidth}%"></span>
    </div>
    <div class="sky-iso__ticks" aria-hidden="true">
      {#each strip.ticks as k (k.left)}<span style:left="{k.left}%">{k.text}</span>{/each}
      <span class="sky-iso__now">Now</span>
    </div>
    {#if coverage?.state === 'error'}
      <div class="sky-iso__load" data-state="error" role="alert">
        <span>Older weeks did not load; they are not zero, just unknown.</span>
        {#if onretry}<button class="sky-iso__retry" type="button" onclick={onretry}>Retry</button>{/if}
      </div>
    {:else if coverage?.state === 'loading'}
      <div class="sky-iso__load" data-state="loading" role="status">Loading older weeks…</div>
    {/if}
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
    container-type: inline-size;
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
    min-width: 0;
  }
  /* From 64rem the readout is a column beside the board, never over it (owner, Oct 10). */
  @container (min-width: 64rem) {
    .sky-iso__stage[data-wide] {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 22rem;
      align-items: start;
      gap: var(--ds-space-4);
    }
    .sky-iso__stage[data-wide] .sky-iso__dock {
      margin-top: 0;
    }
  }
  .sky-iso__chart {
    min-width: 0;
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
  /* Days after today: a floor tile like a quiet day, marked future by a dashed rim (owner, Oct 10: every week is a full column). */
  .sky-iso__future {
    fill: var(--sky-iso-floor);
    fill-opacity: 0.55;
    stroke: var(--sky-iso-label-faint);
    stroke-width: 0.6;
    stroke-dasharray: 2 2;
  }
  /* Not loaded yet: unknown, not zero. */
  .sky-iso__unloaded {
    fill: none;
    stroke: var(--sky-iso-label-faint);
    stroke-width: 0.5;
    stroke-dasharray: 0.5 2.5;
    stroke-linecap: round;
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
    transition: opacity var(--sky-duration-slow) var(--sky-ease-out);
  }
  .sky-iso__chart[data-moving] [data-edge] {
    opacity: 1;
  }
  /* Blocks outside the window the glide is heading for fade and drop; entering ones fade in and rise. */
  .sky-iso__block {
    transition:
      opacity var(--sky-duration-slow) var(--sky-ease-out),
      transform var(--sky-duration-slow) var(--sky-ease-out);
  }
  .sky-iso__block[data-out] {
    opacity: 0;
    transform: translateY(6px);
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
  .sky-iso__hits[data-gliding] {
    transition: transform var(--sky-duration-slow) var(--sky-ease-out);
  }
  /* Pointers pick the visible surface (pickIsoCityBlock); the buttons carry focus and keys. */
  .sky-iso__hit {
    pointer-events: none;
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
  .sky-iso__bar span[data-tone='unknown'] {
    background: transparent;
    border-bottom: 2px dotted var(--sky-iso-label-faint);
  }
  .sky-iso__load {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--ds-space-2);
    font-size: var(--sky-text-data);
    color: var(--ds-color-text-subtle);
  }
  .sky-iso__load[data-state='error'] {
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-iso__retry {
    height: var(--sky-size-control-sm);
    padding: 0 var(--ds-space-3);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    border-radius: var(--sky-radius-control);
    background: transparent;
    color: var(--ds-color-fg);
    font: inherit;
    cursor: pointer;
  }
  .sky-iso__retry:hover {
    border-color: var(--sky-color-border-hover);
  }
  .sky-iso__retry:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  @media (pointer: coarse) {
    .sky-iso__retry {
      height: var(--sky-size-touch);
    }
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
  /* Reduced motion: no translation, one short crossfade per move (two names so each move restarts it). */
  @media (prefers-reduced-motion: reduce) {
    .sky-iso__svg[data-fade='a'] {
      animation: sky-iso-fade-a 180ms ease-out;
    }
    .sky-iso__svg[data-fade='b'] {
      animation: sky-iso-fade-b 180ms ease-out;
    }
  }
  @keyframes sky-iso-fade-a {
    from {
      opacity: 0.35;
    }
  }
  @keyframes sky-iso-fade-b {
    from {
      opacity: 0.35;
    }
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-iso__window {
      transition: left var(--sky-duration-slow) var(--sky-ease-out);
    }
  }
</style>
