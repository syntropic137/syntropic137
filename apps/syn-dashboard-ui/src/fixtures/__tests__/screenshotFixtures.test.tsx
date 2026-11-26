/**
 * The screenshot fixture world (#1647) is the API, as far as a screenshot can
 * tell, so three things must hold:
 *
 * - the committed `fixtures/screenshot.json` is what the module writes now;
 * - every fixture answers a route the OpenAPI spec serves, at a pathname that
 *   route matches (a renamed route must break the set, not 404 silently);
 * - the pages render it populated. The execution page is served the world the
 *   way `screenshot.mjs --fixtures` serves it, by pathname through `fetch`, and
 *   must show the API's per-model cost text at the execution and on each phase.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { API_BASE } from '../../api/base'
import {
  COMPLETED_EXECUTION_ID,
  SCREENSHOT_FIXTURES,
  screenshotFixturesJson,
} from '../screenshotFixtures'

vi.mock('../../hooks/useExecutionStream', () => ({
  useExecutionStream: () => ({ isConnected: false, lastEvent: null, error: null }),
}))

const { ExecutionDetail } = await import('../../pages/ExecutionDetail')

// Vitest runs from the package root; jsdom makes import.meta.url a non-file URL.
const COMMITTED_JSON = resolve(process.cwd(), 'fixtures/screenshot.json')
const OPENAPI_SPEC = resolve(process.cwd(), '../syn-docs/openapi.json')

interface OpenApiSpec {
  paths: Record<string, { get?: unknown }>
}

function specGetRoutes(): Set<string> {
  const spec = JSON.parse(readFileSync(OPENAPI_SPEC, 'utf-8')) as OpenApiSpec
  return new Set(Object.entries(spec.paths).filter(([, ops]) => ops.get !== undefined).map(([path]) => path))
}

/** `/executions/{execution_id}` as a pattern for the pathname the browser asks for. */
function pathnamePattern(route: string): RegExp {
  const escaped = route.replace(/[.*+?^$()|[\]\\]/g, '\\$&').replace(/\\?\{\w+\\?\}/g, '[^/]+')
  return new RegExp(`^${API_BASE.replace(/[/]/g, '\\/')}${escaped}$`)
}

describe('screenshot fixtures', () => {
  it('fixtures/screenshot.json is current; regenerate it with pnpm fixtures:screenshot', () => {
    expect(readFileSync(COMMITTED_JSON, 'utf-8')).toBe(screenshotFixturesJson())
  })

  it('answers only GET routes the OpenAPI spec serves', () => {
    const routes = specGetRoutes()
    const unknown = SCREENSHOT_FIXTURES.map((f) => f.route).filter((route) => !routes.has(route))
    expect(unknown).toEqual([])
  })

  it('serves each fixture at a pathname its route matches', () => {
    const mismatched = SCREENSHOT_FIXTURES.filter((f) => !pathnamePattern(f.route).test(f.pathname))
    expect(mismatched.map((f) => `${f.route} -> ${f.pathname}`)).toEqual([])
  })

  it('refuses two answers for one pathname', () => {
    const [first] = SCREENSHOT_FIXTURES
    expect(() => screenshotFixturesJson([first, first])).toThrow(/two screenshot fixtures answer/)
  })
})

describe('the execution page, served the fixture world by pathname', () => {
  beforeEach(() => {
    const byPathname = new Map(SCREENSHOT_FIXTURES.map((f) => [f.pathname, f.body]))
    // screenshot.mjs's rule: the pathname picks the body, anything else is a 404.
    vi.stubGlobal('fetch', async (input: string | URL | Request) => {
      const url = new URL(input instanceof Request ? input.url : String(input), 'http://localhost')
      const body = byPathname.get(url.pathname)
      return body === undefined
        ? new Response(JSON.stringify({ detail: `no fixture for ${url.pathname}` }), { status: 404 })
        : new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows the completed run populated, with the API cost text per model and per phase', async () => {
    const { container } = render(
      <MemoryRouter initialEntries={[`/executions/${COMPLETED_EXECUTION_ID}`]}>
        <Routes>
          <Route path="/executions/:executionId" element={<ExecutionDetail />} />
        </Routes>
      </MemoryRouter>,
    )

    // The execution-level fields: total_cost_display, cost_by_model(_display).
    await screen.findByText('Cost by Model')
    const costByModel = container.querySelector('#cost-by-model')
    expect(costByModel?.textContent).toContain('>=$2.26 (partial)')
    expect(costByModel?.textContent).toContain('$1.84')
    expect(costByModel?.textContent).toContain('$0.42')

    // Each priced phase's own cost_by_model_display, as its card's model row
    // ("$1.84 · 100%"). Without it the row shows an em dash; the execution card
    // above shows shares of the total (81%, 19%), so it cannot match these.
    expect(screen.getByText('$1.84 · 100%')).toBeTruthy()
    expect(screen.getByText('$0.42 · 100%')).toBeTruthy()
  })
})
