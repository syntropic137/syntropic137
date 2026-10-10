// @vitest-environment jsdom
// Iso City: motion, picking, keyboard and coverage (codex review of #1856; owner, Oct 10).
import '../../components/_test/setup'
import { fireEvent, render, screen } from '@testing-library/svelte'
import { flushSync } from 'svelte'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ISO_CITY_DESKTOP,
  addDays,
  isoCityCentred,
  isoCityHistory,
  isoCityWeeks,
  layoutIsoCityFloor,
  pickIsoCityBlock,
  pointInPolygon,
  type IsoCityBlock,
  type SkylineDay,
} from '@syn137/skyline-core/geometry'
import IsoCity from './IsoCity.svelte'

const TODAY = '2026-10-09'
const hist = isoCityHistory(TODAY, 52)
// Dense history, sessions cycling 1..30: every day is a block.
const busy: SkylineDay[] = Array.from({ length: 52 * 7 }, (_, i) => ({ date: addDays(hist.start, i), sessions: (i % 30) + 1 })).filter((d) => d.date <= TODAY)
const dims = isoCityCentred(ISO_CITY_DESKTOP)
const FIRST = hist.weeks - dims.win // the window at offset 0

const chart = (c: HTMLElement) => c.querySelector<HTMLElement>('.sky-iso__chart')!
const floorGroup = (c: HTMLElement) => c.querySelector<SVGGElement>('.sky-iso__floor-group')!
const anchorOf = (c: HTMLElement) => Number(chart(c).dataset.anchor)
const dayButtons = (c: HTMLElement) => [...c.querySelectorAll<HTMLButtonElement>('.sky-iso__hit')]
const back = () => fireEvent.click(screen.getByRole('button', { name: 'One month back' }))
const shiftX = (c: HTMLElement) => Number(/translate\((-?[\d.]+)px/.exec(floorGroup(c).style.transform)?.[1] ?? 'NaN')

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('IsoCity glide (owner, Oct 10: fluid scroll)', () => {
  it('keeps the previous window painted while the glide runs, and moves it only on landing', async () => {
    const { container } = render(IsoCity, { days: busy, today: TODAY })
    expect(anchorOf(container)).toBe(FIRST)
    const before = [...container.querySelectorAll('[data-date-block]')].map((g) => g.getAttribute('data-date-block'))
    await back()
    expect(anchorOf(container)).toBe(FIRST)
    expect(floorGroup(container).dataset.gliding).toBeDefined()
    expect(shiftX(container)).toBeGreaterThan(0)
    // Every block of the old window is still in the DOM, mid-glide.
    const during = new Set([...container.querySelectorAll('[data-date-block]')].map((g) => g.getAttribute('data-date-block')))
    for (const d of before) expect(during.has(d)).toBe(true)
    await fireEvent.transitionEnd(floorGroup(container), { propertyName: 'transform' })
    expect(anchorOf(container)).toBeLessThan(FIRST)
    expect(floorGroup(container).style.transform).toBe('translate(0px, 0px)')
    expect(floorGroup(container).dataset.gliding).toBeUndefined()
  })

  it('ignores transitionend bubbling from a block fade', async () => {
    const { container } = render(IsoCity, { days: busy, today: TODAY })
    await back()
    await fireEvent.transitionEnd(container.querySelector('.sky-iso__block')!, { propertyName: 'opacity' })
    expect(anchorOf(container)).toBe(FIRST)
  })

  it('retargets a glide in progress without resetting it', async () => {
    const { container } = render(IsoCity, { days: busy, today: TODAY })
    await back()
    const one = shiftX(container)
    await back()
    expect(anchorOf(container)).toBe(FIRST)
    expect(floorGroup(container).dataset.gliding).toBeDefined()
    expect(shiftX(container)).toBeGreaterThan(one)
    // A wheel step mid-glide also joins it.
    await fireEvent.wheel(chart(container), { deltaX: -120, deltaY: 0 })
    expect(anchorOf(container)).toBe(FIRST)
    expect(shiftX(container)).toBeGreaterThan(one * 1.5)
  })

  it('fades edge weeks: buffer blocks carry data-out and are never focusable; leaving and entering blocks swap', async () => {
    const { container } = render(IsoCity, { days: busy, today: TODAY })
    const out = () => [...container.querySelectorAll<SVGGElement>('[data-date-block][data-out]')].map((g) => g.dataset.dateBlock!)
    // At rest: two buffer weeks on the left (nothing after today's week on the right).
    expect(out()).toHaveLength(14)
    const focusable = new Set(dayButtons(container).map((b) => b.dataset.date))
    for (const d of out()) expect(focusable.has(d)).toBe(false)
    const newest = addDays(hist.start, hist.weeks * 7 - 7) // Monday of today's week
    expect(out()).not.toContain(newest)
    await back()
    // Mid-glide: today's week is leaving (fading out), older weeks entering (fading in).
    expect(out()).toContain(newest)
    expect(out().length).toBeGreaterThan(0)
    expect(container.querySelector(`[data-date-block="${addDays(hist.start, (FIRST - 1) * 7)}"]`)?.hasAttribute('data-out')).toBe(false)
  })

  it('never re-lays out the floor mid-glide when an older page of data arrives', async () => {
    const recent = busy.filter((d) => d.date >= addDays(hist.start, FIRST * 7))
    const { container, rerender } = render(IsoCity, { days: recent, today: TODAY })
    await back()
    await rerender({ days: busy, today: TODAY })
    expect(anchorOf(container)).toBe(FIRST)
  })

  it('reduced motion: lands at once and crossfades, no translation', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }))
    const { container } = render(IsoCity, { days: busy, today: TODAY })
    await back()
    expect(anchorOf(container)).toBeLessThan(FIRST)
    expect(floorGroup(container).style.transform).toBe('translate(0px, 0px)')
    expect(container.querySelector<SVGElement>('.sky-iso__svg')?.dataset.fade).toBe('a')
    await back()
    expect(container.querySelector<SVGElement>('.sky-iso__svg')?.dataset.fade).toBe('b')
  })
})

describe('IsoCity cleanup (codex review of #1856: animation callbacks after unmount)', () => {
  it('lands by the backstop when transitionend never comes', async () => {
    vi.useFakeTimers()
    const { container } = render(IsoCity, { days: busy, today: TODAY })
    await back()
    expect(anchorOf(container)).toBe(FIRST)
    await vi.advanceTimersByTimeAsync(600)
    expect(anchorOf(container)).toBeLessThan(FIRST)
  })

  it('cancels every timer and frame on unmount and on a superseding glide', () => {
    vi.useFakeTimers()
    const raf = vi.spyOn(globalThis, 'requestAnimationFrame')
    const { container, unmount } = render(IsoCity, { days: busy, today: TODAY })
    // Native clicks plus flushSync; Svelte's event delegation queues a 0 ms timer of its own, so run those.
    const press = () => {
      screen.getByRole('button', { name: 'One month back' }).click()
      flushSync()
      vi.advanceTimersByTime(0)
    }
    expect(vi.getTimerCount()).toBe(0)
    press()
    expect(vi.getTimerCount()).toBe(1)
    press()
    // The retarget replaced the backstop rather than adding one.
    expect(vi.getTimerCount()).toBe(1)
    expect(anchorOf(container)).toBe(FIRST)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
    expect(raf).not.toHaveBeenCalled()
  })
})

describe('IsoCity keyboard (codex review of #1856)', () => {
  it('keeps exactly one visible day as the Tab stop after scrolling, apart from the selection', async () => {
    const { container } = render(IsoCity, { days: busy, today: TODAY, selected: '2026-10-05' })
    const stops = () => dayButtons(container).filter((b) => b.tabIndex === 0)
    expect(stops().map((b) => b.dataset.date)).toEqual(['2026-10-05'])
    for (let i = 0; i < 3; i++) {
      await back()
      await fireEvent.transitionEnd(floorGroup(container), { propertyName: 'transform' })
      expect(stops()).toHaveLength(1)
    }
    // The selection did not move, but the Tab stop is a day in view.
    expect(stops()[0]!.dataset.date).not.toBe('2026-10-05')
    expect(dayButtons(container).some((b) => b.dataset.date === '2026-10-05')).toBe(false)
  })

  it('scrolls a month with the arrows on the chart and steps days on a day', async () => {
    const { container } = render(IsoCity, { days: busy, today: TODAY, selected: '2026-10-05' })
    await fireEvent.keyDown(chart(container), { key: 'ArrowLeft' })
    expect(screen.getByRole('button', { name: 'One month forward' }).hasAttribute('disabled')).toBe(false)
    await fireEvent.keyDown(chart(container), { key: 'End' })
    await fireEvent.transitionEnd(floorGroup(container), { propertyName: 'transform' })
    const day = container.querySelector<HTMLButtonElement>('[data-date="2026-10-05"]')!
    await fireEvent.keyDown(day, { key: 'ArrowRight' })
    expect(container.querySelector('[data-date="2026-10-06"]')?.getAttribute('aria-pressed')).toBe('true')
  })
})

describe('IsoCity pointing (codex review of #1856: wrong hover/readout day)', () => {
  it('picks the visible surface where the old rectangles picked another day', async () => {
    const { container } = render(IsoCity, { days: busy, today: TODAY })
    const el = chart(container)
    el.getBoundingClientRect = () => ({ left: 0, top: 0, width: dims.vw, height: dims.vh, right: dims.vw, bottom: dims.vh, x: 0, y: 0, toJSON() {} })
    const l = layoutIsoCityFloor({ weeks: isoCityWeeks(busy, hist.start, hist.weeks), first: FIRST, today: TODAY, dims, pad: 2 })
    const shown = l.blocks.filter((b) => b.inWindow)
    const rect = (x: number, y: number) => {
      let best: IsoCityBlock | null = null
      for (const b of shown) if (x >= b.hit.x && x <= b.hit.x + b.hit.width && y >= b.hit.y && y <= b.hit.y + b.hit.height && (!best || b.z >= best.z)) best = b
      return best
    }
    let checked = 0
    for (const b of shown) {
      for (const [x, y] of b.faces[2]!.map(([px, py]) => [px + 0.8, py] as const)) {
        const want = pickIsoCityBlock(l.blocks, x, y)
        if (!want || rect(x, y)?.date === want.date || !b.faces.some((f) => pointInPolygon(x, y, f))) continue
        const ev = new MouseEvent('pointermove', { clientX: x, clientY: y, bubbles: true })
        Object.defineProperties(ev, { pointerType: { value: 'mouse' }, pointerId: { value: 1 } })
        await fireEvent(el, ev)
        expect(container.querySelector('.sky-iso__hit[aria-pressed="true"]')?.getAttribute('data-date')).toBe(want.date)
        checked++
        if (checked >= 6) return
      }
    }
    expect(checked).toBeGreaterThan(0)
  })
})

describe('IsoCity coverage (codex review of #1856: unloaded history is not zero)', () => {
  it('labels unloaded weeks, never 0 sessions, and offers Retry on a failed older page', async () => {
    const onretry = vi.fn()
    const from = addDays(hist.start, 26 * 7)
    const { container } = render(IsoCity, { days: busy.filter((d) => d.date >= from), today: TODAY, coverage: { from, state: 'error' }, onretry })
    const first = container.querySelector<HTMLButtonElement>('.sky-iso__bar')!
    expect(first.getAttribute('aria-label')).toBe('Week of Oct 13: did not load')
    expect(first.dataset.status).toBe('error')
    await fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onretry).toHaveBeenCalledOnce()
  })

  it('says loading while the older page is on its way', () => {
    const from = addDays(hist.start, 26 * 7)
    const { container } = render(IsoCity, { days: busy, today: TODAY, coverage: { from, state: 'loading' } })
    expect(container.querySelector('.sky-iso__load')?.textContent).toBe('Loading older weeks…')
    expect(screen.getAllByRole('button', { name: /: loading$/ }).length).toBe(26)
  })
})

describe('IsoCity board column (owner, Oct 10: the readout never covers today)', () => {
  /** A ResizeObserver that reports the board column at `px`. */
  function columnAt(px: number) {
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(private cb: ResizeObserverCallback) {}
        observe(el: Element) {
          this.cb([{ target: el, contentRect: { width: px } } as unknown as ResizeObserverEntry], this as unknown as ResizeObserver)
        }
        unobserve() {}
        disconnect() {}
      },
    )
  }
  const xsOf = (d: string | null) => [...(d ?? '').matchAll(/(-?[\d.]+),(-?[\d.]+)/g)].map((m) => Number(m[1]))

  // Board column widths at 1280 and 1920 viewports: page gutters and the 22rem readout column taken off.
  it.each([
    [1280, 1280 - 2 * 40 - 352 - 16 - 64],
    [1920, 1920 - 2 * 40 - 352 - 16 - 64],
  ])('at a %ipx viewport the newest column ends more than one cell inside the board column', async (_vp, column) => {
    columnAt(column)
    const { container } = render(IsoCity, { days: busy, today: TODAY })
    await Promise.resolve()
    const svg = container.querySelector<SVGSVGElement>('.sky-iso__svg')!
    const vw = Number(svg.getAttribute('viewBox')!.split(' ')[2])
    const scale = column / vw
    const painted = [
      ...[...container.querySelectorAll('.sky-iso__block:not([data-out]) path')].map((p) => p.getAttribute('d')),
      container.querySelector('.sky-iso__future:not([data-edge])')!.getAttribute('d'),
      container.querySelector('.sky-iso__floor:not([data-edge])')!.getAttribute('d'),
      container.querySelector('.sky-iso__today')!.getAttribute('d'),
    ].flatMap(xsOf)
    const right = Math.max(...painted) * scale
    const cell = 52 * scale
    expect(vw).toBe(column)
    expect(right).toBeLessThan(column - cell)
    // Today's week, future tiles included, is the newest column painted.
    expect(container.querySelector('.sky-iso__future:not([data-edge])')!.getAttribute('d')).toMatch(/^M/)
  })
})

describe('IsoCity, codex review 2 of #1856', () => {
  // jsdom lacks pointer capture; give it a no-op so the drag path runs as in a browser.
  if (!('setPointerCapture' in HTMLElement.prototype)) Object.assign(HTMLElement.prototype, { setPointerCapture() {}, releasePointerCapture() {} })
  const polysOf = (g: Element) =>
    [...g.querySelectorAll('path')].map((p) => [...(p.getAttribute('d') ?? '').matchAll(/(-?[\d.]+),(-?[\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])] as [number, number]))
  /** The day whose surface is painted on top at (x, y): the last block group in document order covering it (any overlay included). */
  function paintedAt(c: HTMLElement, x: number, y: number): string | null {
    let top: string | null = null
    for (const g of c.querySelectorAll<SVGGElement>('.sky-iso__block:not([data-out]), .sky-iso__sel')) {
      if (polysOf(g).some((p) => pointInPolygon(x, y, p))) top = g.dataset.dateBlock ?? 'selected-overlay'
    }
    return top
  }
  const pointer = (type: string, x: number, extra: Record<string, unknown> = {}) => {
    const ev = new MouseEvent(type, { clientX: x, clientY: 100, bubbles: true, button: 0 })
    Object.defineProperties(ev, { pointerType: { value: 'touch' }, pointerId: { value: 7 }, ...Object.fromEntries(Object.entries(extra).map(([k, v]) => [k, { value: v }])) })
    return ev
  }

  it('paints the selection in painter order, so what is painted on top is what a pointer picks', () => {
    const selectedDay = '2026-07-14'
    const { container } = render(IsoCity, { days: busy, today: TODAY, selected: selectedDay })
    const l = layoutIsoCityFloor({ weeks: isoCityWeeks(busy, hist.start, hist.weeks), first: FIRST, today: TODAY, dims, pad: 2, selected: selectedDay })
    const sel = l.blocks.find((b) => b.date === selectedDay)!
    let occluded = 0
    let visible = 0
    // A 2-unit grid: a quarter of the points, still dozens on each face. Every
    // point took 5.1 s on the CI runner against vitest's 5 s limit.
    for (let x = sel.hit.x; x <= sel.hit.x + sel.hit.width; x += 2) {
      for (let y = sel.hit.y; y <= sel.hit.y + sel.hit.height; y += 2) {
        if (!sel.faces.some((f) => pointInPolygon(x, y, f))) continue
        const picked = pickIsoCityBlock(l.blocks, x, y)?.date ?? null
        const painted = paintedAt(container, x, y)
        expect(painted, `${x},${y}`).toBe(picked)
        if (picked === selectedDay) visible++
        else occluded++
      }
    }
    // The probe covers both cases: the selected day's own visible surface, and points a nearer block covers.
    expect(visible).toBeGreaterThan(0)
    expect(occluded).toBeGreaterThan(0)
    expect(container.querySelector(`[data-date-block="${selectedDay}"]`)?.hasAttribute('data-selected')).toBe(true)
  })

  it('freezes the painted paths and the height scale while the floor moves, and swaps both on landing', async () => {
    const recent = busy.filter((d) => d.date >= addDays(hist.start, FIRST * 7))
    const { container, rerender } = render(IsoCity, { days: recent, today: TODAY })
    const top = () => container.querySelector('[data-date-block="2026-09-04"] .sky-iso__top')!.getAttribute('d')
    const before = top()
    await back()
    expect(chart(container).dataset.moving).toBeDefined()
    // An older page arrives mid-glide with a far busier day: the height scale would drop every block.
    const older: SkylineDay = { date: addDays(hist.start, (FIRST - 3) * 7 + 2), sessions: 10_000 }
    await rerender({ days: [...busy, older], today: TODAY })
    expect(chart(container).dataset.moving).toBeDefined()
    expect(top()).toBe(before)
    expect(container.querySelector(`[data-date-block="${older.date}"]`)).toBeNull()
    await fireEvent.transitionEnd(floorGroup(container), { propertyName: 'transform' })
    expect(top()).not.toBe(before)
  })

  it('hands focus to the chart when the focused day scrolls out (never to body)', async () => {
    const { container } = render(IsoCity, { days: busy, today: TODAY, selected: '2026-10-05' })
    const day = container.querySelector<HTMLButtonElement>('[data-date="2026-10-05"]')!
    day.focus()
    expect(document.activeElement).toBe(day)
    await fireEvent.keyDown(day, { key: 'PageUp' })
    expect(container.querySelector('[data-date="2026-10-05"]')).toBeNull()
    expect(document.activeElement).toBe(chart(container))
  })

  it('a drag that starts mid-glide begins from the displayed transform and keeps the anchor', async () => {
    const { container } = render(IsoCity, { days: busy, today: TODAY })
    await back()
    const glidingTo = shiftX(container)
    expect(glidingTo).toBeGreaterThan(0)
    // Mid-transition the floor is drawn 60% of the way there; jsdom has no transitions, so report it.
    const shown = Math.round(glidingTo * 0.6)
    const real = window.getComputedStyle
    vi.spyOn(window, 'getComputedStyle').mockImplementation((el, p) => {
      const s = real(el, p)
      if (el !== floorGroup(container)) return s
      return { ...s, transform: `matrix(1, 0, 0, 1, ${shown}, ${shown * (7 / 52)})` } as CSSStyleDeclaration
    })
    const el = chart(container)
    await fireEvent(el, pointer('pointerdown', 500))
    await fireEvent(el, pointer('pointermove', 510))
    expect(anchorOf(container)).toBe(FIRST)
    expect(shiftX(container)).toBeCloseTo(shown + 10, 0)
    expect(floorGroup(container).dataset.gliding).toBeUndefined()
  })

  it('reduced motion: a drag release lands at once, with no glide back', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }))
    const { container } = render(IsoCity, { days: busy, today: TODAY })
    const el = chart(container)
    await fireEvent(el, pointer('pointerdown', 500))
    await fireEvent(el, pointer('pointermove', 520))
    expect(shiftX(container)).toBeCloseTo(20, 0)
    await fireEvent(el, pointer('pointerup', 520))
    expect(floorGroup(container).dataset.gliding).toBeUndefined()
    expect(floorGroup(container).style.transform).toBe('translate(0px, 0px)')
    expect(anchorOf(container)).toBe(FIRST)
  })
})
