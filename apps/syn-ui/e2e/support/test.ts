/**
 * The suite's `test`: Playwright's, plus
 *
 * - `consoleErrors`: an automatic fixture that fails any test whose page
 *   logged a console error or threw an uncaught exception;
 * - helpers that hide the few selectors the two apps cannot share.
 *
 * Selectors use roles, names and text only, never classes, so the same
 * specs run against syn-ui and apps/syn-dashboard-ui.
 */
import { test as base, expect, type Locator, type Page } from '@playwright/test'
import { BASE_URL, CONSOLE_IGNORE, isFixtures, isSkyline } from './env'
import { DETAIL_LINK, FIXTURE_IDS, type IdKind, type RouteCase } from './routes'

export { expect }

export const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: [
    async ({ page, baseURL }, use, testInfo) => {
      const errors: string[] = []
      const origin = new URL(baseURL ?? BASE_URL).origin
      // Third-party requests (Google Fonts) are not part of the app under test
      // and are unreachable in sandboxed CI: answer them empty so the page
      // neither waits on them nor logs their failure.
      if (!process.env.E2E_ALLOW_THIRD_PARTY) {
        await page.route(
          (url) => url.origin !== origin && (url.protocol === 'http:' || url.protocol === 'https:'),
          (route) => route.fulfill({ status: 200, body: '', contentType: route.request().resourceType() === 'stylesheet' ? 'text/css' : 'text/plain' }),
        )
      }
      page.on('console', (msg) => {
        if (msg.type() !== 'error') return
        const where = msg.location().url
        if (where && /^https?:/.test(where) && new URL(where).origin !== origin) return
        const text = msg.text()
        if (CONSOLE_IGNORE?.test(text)) return
        errors.push(`console.error: ${text}`)
      })
      page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`))
      await use(errors)
      if (errors.length) {
        await testInfo.attach('console-errors', { body: errors.join('\n'), contentType: 'text/plain' })
      }
      expect(errors, 'the page logged console errors').toEqual([])
    },
    { auto: true },
  ],
})

/** App path -> URL relative to the base, so a deploy base such as /next/ is kept. */
export function rel(path: string): string {
  return path.replace(/^\//, '') || './'
}

/** App path of the current page, without the deploy base. */
export function appPath(page: Page, baseURL: string): string {
  const base = new URL(baseURL).pathname.replace(/\/$/, '')
  const p = new URL(page.url()).pathname
  return (p.startsWith(base) ? p.slice(base.length) : p) || '/'
}

/** Escape a string for a RegExp. */
export const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** URL matcher for an app path under any base. */
export function urlFor(path: string): RegExp {
  return path === '/' ? /^[^?#]*\/(\?.*)?(#.*)?$/ : new RegExp(`${esc(path)}/?([?#].*)?$`)
}

export function mainHeading(page: Page): Locator {
  return page.getByRole('heading', { level: 1 }).first()
}

/** The visible primary navigation (capsule on desktop, dock on phone). */
export function primaryNav(page: Page): Locator {
  if (isSkyline) return page.getByRole('navigation', { name: 'Primary' })
  return page.getByRole('navigation').filter({ has: page.getByRole('link', { name: 'Executions', exact: true }) }).first()
}

/** The breadcrumb trail. React's trail has no accessible name, so it is found by its parent link. */
export function breadcrumbs(page: Page, parentLabel?: string | RegExp): Locator {
  if (isSkyline) return page.getByRole('navigation', { name: 'Breadcrumb' })
  const navs = page.getByRole('navigation')
  return (parentLabel ? navs.filter({ has: page.getByRole('link', { name: parentLabel }) }) : navs).last()
}

/**
 * The ID a detail route uses: E2E_ID_<KIND>, else the fixture ID, else the
 * first detail link on the list page (live data).
 */
export async function resolveId(page: Page, kind: IdKind, listPath: string): Promise<string> {
  const env = process.env[`E2E_ID_${kind.toUpperCase()}`]
  if (env) return env
  if (isFixtures) return FIXTURE_IDS[kind]
  await page.goto(rel(listPath))
  const id = await firstDetailId(page, kind)
  if (!id) throw new Error(`No ${kind} link on ${listPath}; set E2E_ID_${kind.toUpperCase()}`)
  return id
}

/** First link on the page whose href is a `kind` detail URL, or null. */
export async function firstDetailId(page: Page, kind: IdKind, timeout = 10_000): Promise<string | null> {
  const pattern = DETAIL_LINK[kind]
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const hrefs = await page.locator('a[href]').evaluateAll((as) => as.map((a) => new URL((a as HTMLAnchorElement).href).pathname))
    for (const h of hrefs) {
      const m = pattern.exec(h)
      if (m && m[1] !== 'runs') return decodeURIComponent(m[1])
    }
    await page.waitForTimeout(250)
  }
  return null
}

/** Resolve a route case to an app path. */
export async function pathFor(page: Page, route: RouteCase): Promise<string> {
  if (!route.id) return route.path
  const id = await resolveId(page, route.id, route.listPath ?? '/')
  return route.path.replace(':id', encodeURIComponent(id))
}

/** Open a route and wait for its page heading. */
export async function open(page: Page, path: string): Promise<void> {
  await page.goto(rel(path))
  await expect(mainHeading(page)).toBeVisible({ timeout: 15_000 })
}

/** Horizontal overflow of the page in CSS px (0 when nothing scrolls sideways). */
export async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => {
    const doc = document.documentElement
    return Math.max(doc.scrollWidth, document.body.scrollWidth) - doc.clientWidth
  })
}

/** overflow-x values that contain a wide descendant (it scrolls or clips on its own). */
const CONTAINING_OVERFLOW = ['auto', 'scroll', 'hidden', 'clip']

/** An element sticking out past the viewport, with its ancestors' overflow-x up to <body>. */
interface OverflowCandidate {
  tag: string
  className: string
  right: number
  ancestorOverflowX: string[]
}

/** Elements wider than the viewport, for a readable failure message. */
export async function overflowingElements(page: Page): Promise<string[]> {
  const candidates = await page.evaluate(overflowCandidates)
  // Skip descendants of an element that scrolls on its own.
  return candidates
    .filter((c) => !c.ancestorOverflowX.some((ox) => CONTAINING_OVERFLOW.includes(ox)))
    .slice(0, 5)
    .map((c) => `${c.tag}${c.className ? '.' + c.className.split(' ')[0] : ''} right=${Math.round(c.right)}`)
}

/** Runs in the browser (serialised by page.evaluate), so it must be self-contained. */
function overflowCandidates(): OverflowCandidate[] {
  const w = document.documentElement.clientWidth
  const out: OverflowCandidate[] = []
  for (const el of Array.from(document.body.querySelectorAll<HTMLElement>('*'))) {
    const r = el.getBoundingClientRect()
    if (r.right <= w + 1 || r.width <= 0) continue
    const ancestorOverflowX: string[] = []
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) ancestorOverflowX.push(getComputedStyle(p).overflowX)
    out.push({ tag: el.tagName.toLowerCase(), className: typeof el.className === 'string' ? el.className : '', right: r.right, ancestorOverflowX })
  }
  return out
}

/** Mark the window so a later check can prove navigation stayed client-side. */
export async function markWindow(page: Page): Promise<void> {
  await page.evaluate(() => ((window as unknown as { __e2e: number }).__e2e = 1))
}

export async function windowStillMarked(page: Page): Promise<boolean> {
  return page.evaluate(() => (window as unknown as { __e2e?: number }).__e2e === 1)
}
