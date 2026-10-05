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

/**
 * A 200 whose headers arrive and whose body never finishes: the gateway logs it
 * as answered, the browser is still reading it. Like a real fetch, aborting the
 * request errors the body.
 */
function stalledBody(init?: RequestInit): Promise<Response> {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('{"items":['))
      init?.signal?.addEventListener('abort', () => controller.error(new DOMException('aborted', 'AbortError')))
    },
  })
  return Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'application/json' } }))
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

  it('logs each request with a running count per endpoint in development', async () => {
    const debug = vi.spyOn(console, 'debug').mockImplementation(() => {})
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => json(isStats(String(input)) ? STATS : listBody('item'))),
    )
    const logged = (path: string) =>
      debug.mock.calls.map(([line]) => String(line)).filter((line) => line.startsWith(`[ui-feedback] GET ${path} #`))

    renderList()
    await screen.findByText('item 0')
    const listBefore = logged('/api/v1/feedback').length
    fireEvent.click(screen.getByText('Refresh'))
    await waitFor(() => expect(logged('/api/v1/feedback')).toHaveLength(listBefore + 1))

    // One running count per endpoint: the query string is not part of the key,
    // and the module-level count carries on from earlier tests.
    const counts = logged('/api/v1/feedback').map((line) => Number(line.split('#')[1]))
    expect(counts.at(-1)).toBe(counts.at(-2)! + 1)
    expect(logged('/api/v1/feedback/stats').length).toBeGreaterThan(0)
    debug.mockRestore()
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

  it('turns a 200 whose body stalls into an error with Retry', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
        isList(String(input)) ? stalledBody(init) : Promise.resolve(json(STATS)),
      ),
    )

    renderList()
    await act(() => vi.advanceTimersByTimeAsync(15_000))

    expect(screen.queryByText('Loading feedback...')).toBeNull()
    expect(screen.getByText(/did not respond within 15s/)).toBeTruthy()
    expect(screen.getByText('Retry')).toBeTruthy()
  })

  it('cancels a superseded load, so one request per endpoint is ever in flight', async () => {
    const active = { list: 0, stats: 0 }
    const peak = { list: 0, stats: 0 }
    let releaseNext: Array<() => void> = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const kind = isStats(String(input)) ? 'stats' : 'list'
        active[kind] += 1
        peak[kind] = Math.max(peak[kind], active[kind])
        return new Promise<Response>((resolve, reject) => {
          const settle = () => { active[kind] -= 1 }
          init?.signal?.addEventListener('abort', () => { settle(); reject(new DOMException('aborted', 'AbortError')) })
          releaseNext.push(() => {
            if (init?.signal?.aborted) return
            settle()
            resolve(json(kind === 'stats' ? STATS : listBody('item', 3)))
          })
        })
      }),
    )

    renderList()
    fireEvent.click(screen.getByText('Refresh'))
    fireEvent.click(screen.getByText('Refresh'))
    expect(peak).toEqual({ list: 1, stats: 1 })

    await act(async () => { releaseNext.forEach((r) => r()); releaseNext = [] })
    await screen.findByText('item 2')
    expect(active).toEqual({ list: 0, stats: 0 })
    expect(peak).toEqual({ list: 1, stats: 1 })
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
