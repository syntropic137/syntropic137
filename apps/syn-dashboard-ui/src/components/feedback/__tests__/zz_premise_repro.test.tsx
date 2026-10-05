import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../../App'

class InertEventSource {
  close(): void {}
  addEventListener(): void {}
  removeEventListener(): void {}
}

function makeItem(i: number) {
  return {
    id: String(i),
    url: 'https://example.com/executions/abc',
    feedback_type: 'bug',
    comment: `item ${i}`,
    status: 'open',
    priority: 'low',
    app_name: 'syn-dashboard-ui',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    media_count: 0,
  }
}

function stubApi() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    let body: unknown
    if (url.includes('/features')) {
      body = { ui_feedback: true }
    } else if (url.includes('/feedback/stats')) {
      body = {
        total: 20,
        by_status: { open: 5, in_progress: 0, resolved: 0, closed: 15, wont_fix: 0 },
        by_type: {},
        by_priority: {},
        by_app: {},
      }
    } else if (url.includes('/feedback')) {
      body = {
        items: Array.from({ length: 20 }, (_, i) => makeItem(i)),
        page: 1,
        page_size: 50,
        total: 20,
      }
    } else {
      body = { items: [], total: 0, page: 1, page_size: 50, by_status: {} }
    }
    const delay = url.includes('/feedback/stats') ? 600 : url.includes('/feedback') ? 1000 : 0
    await new Promise((r) => setTimeout(r, delay))
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('EventSource', InertEventSource)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('premise repro: View Tickets loop', () => {
  it('calls listFeedback exactly once per open and renders the 20 items', async () => {
    const fetchMock = stubApi()
    const user = userEvent.setup()

    window.history.pushState({}, '', '/executions')
    render(<App />)

    await waitFor(
      () => expect(screen.getByTitle(/^Feedback \(/)).toBeTruthy(),
      { timeout: 10_000 },
    )

    await user.click(screen.getByTitle(/^Feedback \(/))
    await user.click(screen.getByText('View Tickets'))

    await waitFor(() => expect(screen.getByText('item 0')).toBeTruthy(), { timeout: 10_000 })

    // Give any stray re-render loop a window to show itself.
    await new Promise((resolve) => setTimeout(resolve, 1000))

    const listCalls = fetchMock.mock.calls.filter(([url]) => {
      const u = String(url)
      return u.includes('/feedback') && !u.includes('/feedback/stats') && !u.includes('/features')
    })
    const statsCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/feedback/stats'))

    console.log('listFeedback call count:', listCalls.length, listCalls.map(([u]) => String(u)))
    console.log('getStats call count:', statsCalls.length)
    console.log('getStats call timestamps:', fetchMock.mock.invocationCallOrder.filter((_, idx) => String(fetchMock.mock.calls[idx][0]).includes('/feedback/stats')))

    expect(screen.queryByText('Loading feedback...')).toBeNull()
    expect(listCalls.length).toBe(1)
  }, 20_000)
})
