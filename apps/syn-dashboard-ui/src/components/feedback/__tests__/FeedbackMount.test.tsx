/**
 * The feedback widget is mounted once at the app root, and only when the API
 * says the feature is on (#105, ADR-016).
 *
 * Both states are asserted, because the OFF state is the one that ships to
 * open-source users: a regression that renders the widget unconditionally
 * would be invisible to a test that only covers ON.
 *
 * `<App />` is rendered rather than `<FeedbackMount />` alone — the claim
 * under test is "on every page", which is a claim about the root layout, not
 * about the component in isolation. It is rendered at an arbitrary inner
 * route, not at `/`, to make the point that the widget is not something one
 * particular page happens to carry.
 */

import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../../../App'

/**
 * jsdom ships no EventSource, and the root layout opens the activity stream
 * on mount. A stub that connects to nothing keeps that out of the way.
 */
class InertEventSource {
  close(): void {}
  addEventListener(): void {}
  removeEventListener(): void {}
}

/**
 * Answers /features with the given flag and everything else with an empty
 * result. The pages fetch on mount; none of that is what this test is about,
 * so they get a shape they can render nothing from.
 *
 * Returns the mock so a test can assert the flag was actually asked for —
 * "told no" and "has not asked yet" look identical in the DOM.
 */
function stubApi(uiFeedback: boolean) {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const body = String(input).includes('/features')
      ? { ui_feedback: uiFeedback }
      : { items: [], total: 0, page: 1, page_size: 50, by_status: {} }
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })
  vi.stubGlobal('EventSource', InertEventSource)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const FEEDBACK_STATS = {
  total: 3,
  by_status: { open: 3, in_progress: 0, resolved: 0, closed: 0, wont_fix: 0 },
  by_type: {},
  by_priority: {},
  by_app: {},
}

/** The floating button's title is the stable handle the widget exposes. */
const FEEDBACK_BUTTON = /^Feedback \(/

/**
 * Generous: the widget arrives through a dynamic import(), and in the test
 * runner that means transforming the package on demand.
 */
const CHUNK_TIMEOUT = { timeout: 10_000 }
const TEST_TIMEOUT = 20_000

function renderAppAt(path: string) {
  window.history.pushState({}, '', path)
  return render(<App />)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('FeedbackMount', () => {
  it('renders the widget on the root layout when the feature is enabled', async () => {
    stubApi(true)

    renderAppAt('/executions')

    await waitFor(
      () => expect(screen.getByTitle(FEEDBACK_BUTTON)).toBeTruthy(),
      CHUNK_TIMEOUT,
    )
  }, TEST_TIMEOUT)

  it('renders nothing when the feature is disabled', async () => {
    const fetchMock = stubApi(false)

    renderAppAt('/executions')

    await waitFor(() => {
      const asked = fetchMock.mock.calls.some(([url]) =>
        String(url).includes('/features'),
      )
      expect(asked).toBe(true)
    })
    // Long enough that the enabled case above would have rendered by now.
    await new Promise((resolve) => setTimeout(resolve, 1_500))

    expect(screen.queryByTitle(FEEDBACK_BUTTON)).toBeNull()
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes('/feedback')),
    ).toBe(false)
  }, TEST_TIMEOUT)

  it('opens feedback mode on the keyboard shortcut', async () => {
    const user = userEvent.setup()
    stubApi(true)

    renderAppAt('/executions')
    await waitFor(
      () => expect(screen.getByTitle(FEEDBACK_BUTTON)).toBeTruthy(),
      CHUNK_TIMEOUT,
    )

    await user.keyboard('{Control>}{Shift>}F{/Shift}{/Control}')

    // In feedback mode the floating button becomes a cancel button and the
    // pick-an-element overlay takes over the page.
    await waitFor(() =>
      expect(screen.getByTitle('Cancel (Esc)')).toBeTruthy(),
    )
  }, TEST_TIMEOUT)

  /**
   * The owner saw "View Tickets" spin, and the list endpoint called again and
   * again. This drives it the way production renders it: the whole app, a
   * detail route (so the widget has a non-null subject), the bubble's own
   * stats fetch live, the tickets opened from the real widget — and then ten
   * seconds of clock, which is long enough for any render loop or poll to
   * show up as more than one list request.
   */
  it('loads the ticket list once when it is opened, and not again while it sits open', async () => {
    const user = userEvent.setup()
    // The feedback endpoints answer as production did. Everything else is a
    // 404, which the detail page renders as "not found" rather than tripping
    // over an empty body shaped for a list.
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/features')) return jsonResponse({ ui_feedback: true })
      if (url.includes('/feedback/stats')) return jsonResponse(FEEDBACK_STATS)
      if (url.includes('/feedback?')) return jsonResponse({ items: [], total: 0, page: 1, page_size: 50 })
      return jsonResponse({ detail: 'Not found' }, 404)
    })
    vi.stubGlobal('EventSource', InertEventSource)
    vi.stubGlobal('fetch', fetchMock)
    const listCalls = () =>
      fetchMock.mock.calls.filter(([url]) => String(url).includes('/feedback?')).length
    const statsCalls = () =>
      fetchMock.mock.calls.filter(([url]) => String(url).includes('/feedback/stats')).length

    renderAppAt('/executions/exec-1')
    await waitFor(
      () => expect(screen.getByTitle(FEEDBACK_BUTTON)).toBeTruthy(),
      CHUNK_TIMEOUT,
    )
    expect(listCalls()).toBe(0)

    await user.keyboard('{Control>}{Shift>}T{/Shift}{/Control}')
    await waitFor(() => expect(listCalls()).toBe(1))
    const statsAtOpen = statsCalls()

    vi.useFakeTimers()
    try {
      await act(() => vi.advanceTimersByTimeAsync(10_000))
    } finally {
      vi.useRealTimers()
    }

    expect(listCalls()).toBe(1)
    expect(statsCalls()).toBe(statsAtOpen)
  }, TEST_TIMEOUT)
})
