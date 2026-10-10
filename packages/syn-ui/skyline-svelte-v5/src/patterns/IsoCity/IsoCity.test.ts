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
