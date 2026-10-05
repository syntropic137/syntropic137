/**
 * "View Tickets" must end in the tickets or in an error with Retry, never in
 * a spinner that outlives the request (owner report, 2026-10-05).
 *
 * The real `FeedbackList` from the package is rendered against a fetch stub
 * returning the shapes the production API returned, so what is under test is
 * the list the owner saw, not the hook in isolation.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { FeedbackList } from '@syn137/ui-feedback-react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const STATS = {
  total: 20,
  by_status: { open: 5, in_progress: 0, resolved: 0, closed: 15, wont_fix: 0 },
  by_type: {},
  by_priority: {},
  by_app: {},
}

function listBody(label: string, count = 20) {
  const now = new Date().toISOString()
  return {
    items: Array.from({ length: count }, (_, i) => ({
      id: `${label}-${i}`,
      url: 'https://example.com/executions/abc',
      feedback_type: 'bug',
      comment: `${label} ${i}`,
      status: 'open',
      priority: 'low',
      app_name: 'syn-dashboard-ui',
      created_at: now,
      updated_at: now,
      media_count: 0,
    })),
    page: 1,
    page_size: 50,
    total: count,
  }
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

/** A request the server never answers; it ends only when its caller aborts it. */
function never(init?: RequestInit): Promise<Response> {
  return new Promise((_, reject) => {
    init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  })
}

const isList = (url: string) => url.includes('/feedback?')
const isStats = (url: string) => url.includes('/feedback/stats')

function renderList() {
  return render(<FeedbackList apiUrl="/api/v1" appName="syn-dashboard-ui" onClose={() => {}} />)
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('FeedbackList', () => {
  it('renders the tickets from one list request', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      json(isStats(String(input)) ? STATS : listBody('item')),
    )
    vi.stubGlobal('fetch', fetchMock)

    renderList()

    await screen.findByText('item 19')
    expect(screen.queryByText('Loading feedback...')).toBeNull()
    const listCalls = fetchMock.mock.calls.filter(([u]) => isList(String(u)))
    expect(listCalls).toHaveLength(1)
    expect(String(listCalls[0][0])).toBe('/api/v1/feedback?app=syn-dashboard-ui&limit=50')
  })

  it('turns a request that never answers into an error with Retry', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      isList(String(input)) ? never(init) : Promise.resolve(json(STATS)),
    )
    vi.stubGlobal('fetch', fetchMock)

    renderList()
    expect(screen.getByText('Loading feedback...')).toBeTruthy()

    await act(() => vi.advanceTimersByTimeAsync(15_000))

    expect(screen.queryByText('Loading feedback...')).toBeNull()
    expect(screen.getByText(/did not respond within 15s/)).toBeTruthy()

    // Retry reaches the server again, and this time it answers.
    fetchMock.mockImplementation(async (input: RequestInfo | URL) =>
      json(isStats(String(input)) ? STATS : listBody('item')),
    )
    vi.useRealTimers()
    fireEvent.click(screen.getByText('Retry'))
    await screen.findByText('item 0')
  })

  it('keeps the newest load when an older one settles after it', async () => {
    let releaseFirst: (r: Response) => void = () => {}
    let listCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (isStats(url)) return Promise.resolve(json(STATS))
        listCount += 1
        if (listCount === 1) return new Promise<Response>((resolve) => { releaseFirst = resolve })
        return Promise.resolve(json(listBody('newer', 3)))
      }),
    )

    renderList()
    fireEvent.click(screen.getByText('Refresh'))
    await screen.findByText('newer 2')

    await act(async () => releaseFirst(json(listBody('older', 3))))

    await waitFor(() => expect(screen.getByText('newer 0')).toBeTruthy())
    expect(screen.queryByText('older 0')).toBeNull()
  })
})
