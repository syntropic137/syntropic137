/**
 * Landing motion on /dev/patterns (landing plan, section 7): the landing
 * patterns animate only through motion.css (sky-* keyframes), never with
 * reduced motion, and every animation ends (the landing energy test
 * measures idle CPU 35s after load).
 */
import { isSkyline } from './support/env'
import { expect, open, test } from './support/test'

const MOTION = ['sky-rise', 'sky-sdrop', 'sky-pulse', 'sky-flash', 'sky-drift', 'sky-bob', 'sky-type', 'sky-blink', 'sky-draw', 'sky-scroll']

test.skip(!isSkyline, 'dev pages exist only in syn-ui')

async function landingAnimations(page: import('@playwright/test').Page) {
  return page.evaluate((names) => {
    const all: Animation[] = []
    const walk = (root: Document | ShadowRoot) => {
      all.push(...root.getAnimations())
      root.querySelectorAll('*').forEach((el) => el.shadowRoot && walk(el.shadowRoot))
    }
    walk(document)
    return all
      .filter((a): a is CSSAnimation => 'animationName' in a && names.includes((a as CSSAnimation).animationName))
      .map((a) => {
        const t = a.effect?.getComputedTiming()
        return { name: a.animationName, end: Number(t?.endTime ?? Infinity), iterations: Number(t?.iterations ?? Infinity) }
      })
  }, MOTION)
}

test('landing patterns stand still with reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await open(page, '/dev/patterns')
  await page.getByRole('heading', { name: 'Landing: Eval Explorer' }).scrollIntoViewIfNeeded()
  expect(await landingAnimations(page)).toEqual([])
})

test('landing patterns animate a few times, then stop', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await open(page, '/dev/patterns')
  await page.getByRole('heading', { name: 'Landing: Usage Band and Tool Log Ticker' }).scrollIntoViewIfNeeded()
  const anims = await landingAnimations(page)
  expect(new Set(anims.map((a) => a.name))).toEqual(new Set(['sky-rise', 'sky-sdrop', 'sky-pulse', 'sky-flash', 'sky-drift', 'sky-scroll']))
  for (const a of anims) {
    expect(Number.isFinite(a.iterations), `${a.name} loops forever`).toBe(true)
    expect(a.end, `${a.name} ends after 35s`).toBeLessThanOrEqual(35_000)
  }
})
