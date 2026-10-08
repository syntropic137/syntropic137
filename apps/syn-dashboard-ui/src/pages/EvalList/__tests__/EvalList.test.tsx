/**
 * The Evals list over `fetch`, not a mocked hook: the sparkline is joined from
 * a second endpoint (`/evals/{id}/runs`), and that join is half of what is
 * being asserted.
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { evalRun, evalSummary, json, runPage } from '../../../test/evalFixtures'
import { EvalList } from '../EvalList'

function serve(routes: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://x')
    const key = url.pathname.replace('/api/v1', '')
    if (!(key in routes)) return json({ detail: `unrouted ${key}` }, 404)
    return json(routes[key])
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderAt(path = '/evals') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/evals" element={<EvalList />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('EvalList', () => {
  it('renders one row per eval with its pass rate, tags, variants and a sparkline of recent verdicts', async () => {
    serve({
      '/evals': { evals: [evalSummary()], total: 1, page: 1, page_size: 50 },
      '/evals/eval-1/runs': runPage([
        evalRun({ execution_id: 'n', verdict: 'FAIL' }),
        evalRun({ execution_id: 'm', verdict: 'PASS' }),
        evalRun({ execution_id: 'o', verdict: 'ERROR' }),
      ]),
    })
    renderAt()

    const link = await screen.findByRole('link', { name: 'Fix the flaky checkout test' })
    expect(link).toHaveAttribute('href', '/evals/eval-1')
    expect(screen.getAllByText('66.7% (2/3)').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'suite:verifier-seed' })).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Variants' })).getByText(/wf-verifier/)).toBeInTheDocument()

    const spark = await screen.findByRole('img', { name: /Last 3 runs/ })
    // Runs arrive newest first; the sparkline reads oldest to newest.
    expect([...spark.querySelectorAll('rect')].map((r) => r.dataset.verdict)).toEqual(['ERROR', 'PASS', 'FAIL'])
  })

  it('filters by tag through the API when a tag is clicked', async () => {
    const fetchMock = serve({
      '/evals': { evals: [evalSummary({ run_count: 0, variants: [] })], total: 1, page: 1, page_size: 50 },
    })
    renderAt()
    await userEvent.click(await screen.findByRole('button', { name: 'suite:verifier-seed' }))

    await waitFor(() =>
      expect(fetchMock.mock.calls.map(([u]) => String(u))).toContain('/api/v1/evals?tag=suite%3Averifier-seed'),
    )
    expect(await screen.findByRole('button', { name: 'Clear tag filter suite:verifier-seed' })).toBeInTheDocument()
  })

  it('does not ask for runs of an eval that has none', async () => {
    const fetchMock = serve({
      '/evals': { evals: [evalSummary({ run_count: 0, variants: [] })], total: 1, page: 1, page_size: 50 },
    })
    renderAt()
    await screen.findByRole('link', { name: 'Fix the flaky checkout test' })
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/runs'))).toBe(false)
  })

  it('tells an empty platform how evals are created', async () => {
    serve({ '/evals': { evals: [], total: 0, page: 1, page_size: 50 } })
    renderAt()
    expect(await screen.findByText('No evals yet')).toBeInTheDocument()
    expect(screen.getByText(/eval_suite\.py launch/)).toBeInTheDocument()
    expect(screen.getByText(/POST \/evals/)).toBeInTheDocument()
  })

  it('pages past the first 50 evals, so the oldest stay reachable', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      const page = Number(url.searchParams.get('page') ?? '1')
      const only = evalSummary({ eval_id: `eval-p${page}`, name: `Eval on page ${page}`, run_count: 0 })
      return json({ evals: [only], total: 51, page, page_size: 50, status_counts: { active: 51 } })
    })
    vi.stubGlobal('fetch', fetchMock)
    renderAt()

    await screen.findByRole('link', { name: 'Eval on page 1' })
    await userEvent.click(screen.getByRole('button', { name: /Next/ }))

    expect(await screen.findByRole('link', { name: 'Eval on page 2' })).toHaveAttribute('href', '/evals/eval-p2')
    const pages = fetchMock.mock.calls.map(([u]) => new URL(String(u), 'http://x').searchParams.get('page'))
    expect(pages).toContain('2')
  })
})
