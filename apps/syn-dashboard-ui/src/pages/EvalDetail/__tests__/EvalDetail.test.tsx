import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { EvalRun } from '../../../api/evals'
import { LONG_MODEL, evalRun, evalSummary, json, runPage, variant } from '../../../test/evalFixtures'
import { EvalDetail } from '../EvalDetail'

function serve(summary = evalSummary(), runs = runPage([evalRun()])) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = new URL(String(input), 'http://x').pathname
    if (path === '/api/v1/evals/eval-1') return json(summary)
    if (path === '/api/v1/evals/eval-1/runs') return json(runs)
    return json({ detail: 'nope' }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/evals/eval-1']}>
      <Routes>
        <Route path="/evals/:evalId" element={<EvalDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

/** A server that pages `runs` (newest first) the way `/evals/{id}/runs` does. */
function servePaged(runs: EvalRun[]) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://x')
    if (url.pathname === '/api/v1/evals/eval-1') return json(evalSummary({ run_count: runs.length }))
    if (url.pathname !== '/api/v1/evals/eval-1/runs') return json({ detail: 'nope' }, 404)
    const page = Number(url.searchParams.get('page') ?? '1')
    const pageSize = Number(url.searchParams.get('page_size') ?? '50')
    const items = runs.slice((page - 1) * pageSize, page * pageSize)
    return json({ items, total: runs.length, page, page_size: pageSize })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => vi.unstubAllGlobals())

describe('EvalDetail', () => {
  it('shows the header: name, goal, pinned baseline linked at its SHA, tags and the frozen badge', async () => {
    serve()
    renderDetail()
    expect(await screen.findByRole('heading', { level: 1, name: 'Fix the flaky checkout test' })).toBeInTheDocument()
    expect(screen.getByText(/Make tests\/test_checkout\.py pass/)).toBeInTheDocument()
    const baseline = screen.getByRole('link', { name: 'acme/shop@0123456789ab' })
    expect(baseline).toHaveAttribute(
      'href',
      'https://github.com/acme/shop/tree/0123456789abcdef0123456789abcdef01234567',
    )
    expect(screen.getByText('suite:verifier-seed')).toBeInTheDocument()
    expect(screen.getByText('Frozen')).toBeInTheDocument()
  })

  it('has no frozen badge on an eval that is not frozen', async () => {
    serve(evalSummary({ frozen: false }))
    renderDetail()
    await screen.findByRole('heading', { level: 1 })
    expect(screen.queryByText('Frozen')).toBeNull()
  })

  it('compares variants and lists runs that link to their executions with verdict, score and evidence', async () => {
    serve(
      evalSummary({ variants: [variant(), variant({ workflow_id: 'wf-fast', models: [LONG_MODEL] })] }),
      runPage(
        [
          evalRun({ execution_id: 'exec-9', verdict: 'FAIL', score: 0.25, workflow_version: 'sha256:abc' }),
          evalRun({ execution_id: 'exec-8', verdict: null, score: null, evidence_excerpt: null }),
        ],
        120,
      ),
    )
    renderDetail()
    await screen.findByRole('heading', { level: 1 })

    const tables = screen.getAllByRole('table')
    expect(within(tables[0]).getAllByRole('row')).toHaveLength(3)

    const runs = tables[1]
    const links = within(runs).getAllByRole('link')
    expect(links.map((l) => l.getAttribute('href'))).toEqual(['/executions/exec-9', '/executions/exec-8'])
    expect(within(runs).getByText('FAIL')).toBeInTheDocument()
    expect(within(runs).getByText('Unscored')).toBeInTheDocument()
    expect(within(runs).getByText('0.25')).toBeInTheDocument()
    const [, failed] = within(runs).getAllByRole('row')
    expect(failed).toHaveTextContent('wf-verifier @ sha256:abc')
    // Duration, cost and scorer are columns of their own, rendered at every width.
    expect(within(failed).getByText('20m 0s')).toBeInTheDocument()
    expect(within(failed).getByText('$0.41 est.')).toBeInTheDocument()
    expect(within(failed).getByText('eval_suite v2')).toBeInTheDocument()
    expect(within(failed).getByText('20m 0s').closest('td')).not.toHaveClass('hidden')

    const [summary] = within(failed).getAllByText(/All 14 checkout tests passed/)
    await userEvent.click(summary)
    expect(summary.closest('details')).toHaveAttribute('open')
    expect(screen.getByText('Runs 1–50 of 120, newest first')).toBeInTheDocument()

    // The server's total, not the rows on this page.
    expect(screen.getByText('Showing 1-50 of 120 runs')).toBeInTheDocument()
  })

  it('summarises the whole eval from the server, not from the page of runs it shows', async () => {
    // One run on this page; the eval has 120. Every figure in the strip is
    // the eval-level display string, which the page could not have derived
    // from the runs it holds.
    serve(evalSummary({ run_count: 120, scored_count: 97, pass_rate_display: '41% judged' }), runPage([evalRun()], 120))
    renderDetail()
    const strip = await screen.findByRole('region', { name: 'Summary' })

    expect(within(strip).getByText('41% judged')).toBeInTheDocument()
    expect(within(strip).getByText(/ERROR and unscored excluded/)).toBeInTheDocument()
    expect(within(strip).getByText('97 / 120')).toBeInTheDocument()
    expect(within(strip).getByText('over all 120 runs')).toBeInTheDocument()
    expect(within(strip).getByText('18m all')).toBeInTheDocument()
    expect(within(strip).getByText('$0.39 all')).toBeInTheDocument()
    expect(within(strip).getByText('$0.58 all')).toBeInTheDocument()
    expect(screen.getByText('Workflow × version × models, over all 120 runs')).toBeInTheDocument()
  })

  it('keeps every run on the timeline, older than the first page included, while the table pages', async () => {
    const day = 24 * 60 * 60 * 1000
    const newest = Date.parse('2026-10-06T00:00:00Z')
    const runs = Array.from({ length: 260 }, (_, i) =>
      evalRun({ execution_id: `exec-${i}`, started_at: new Date(newest - i * day).toISOString() }),
    )
    servePaged(runs)
    const { container } = renderDetail()
    await screen.findByRole('heading', { level: 1 })

    const markers = () => container.querySelectorAll('svg circle')
    await screen.findByText('All 260 runs, by variant')
    expect(markers()).toHaveLength(260)
    // The oldest run, far past the table's first page, is on the chart.
    expect([...markers()].some((c) => c.textContent?.includes('exec-259'))).toBe(true)

    const table = () => screen.getAllByRole('table')[1]
    expect(within(table()).getAllByRole('link')[0]).toHaveAttribute('href', '/executions/exec-0')
    await userEvent.click(screen.getByRole('button', { name: /Next/ }))
    await waitFor(() =>
      expect(within(table()).getAllByRole('link')[0]).toHaveAttribute('href', '/executions/exec-50'),
    )
    expect(markers()).toHaveLength(260)
    // Two timeline pages, 260 markers and two table renders: past vitest's 5s
    // default when the suite runs in parallel, nowhere near it alone.
  }, 20_000)

  it('reports a failed load instead of an empty page', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'Eval not found' }, 404)))
    renderDetail()
    expect(await screen.findByText('Could not load this eval')).toBeInTheDocument()
    expect(screen.getByText('Eval not found')).toBeInTheDocument()
  })
})
