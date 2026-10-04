/**
 * The feedback form's keyboard flow and defaults, asserted where they land.
 *
 * Driven through the package's public surface (`FeedbackProvider` +
 * `FeedbackWidget`, opened with the widget's own Ctrl+Shift+Q), and read back
 * from the POST body the widget sends. A default that the form state holds but
 * the request drops, or a hotkey that changes the badge but not the payload,
 * fails here.
 *
 * The ticket-list filter bar is checked against the real stylesheet loaded into
 * jsdom. jsdom does no layout, so what is asserted at each width is the cascade
 * that decides layout (wrap, no shrink, no sideways scroll), not pixels.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FeedbackProvider, FeedbackWidget } from '@syn137/ui-feedback-react'

const API = 'http://feedback.test/api'

const STATS = {
  total: 7,
  by_status: { open: 3, in_progress: 1, resolved: 1, closed: 1, wont_fix: 1 },
  by_type: {},
  by_priority: {},
  by_app: {},
}

type Posted = { feedback_type: string; priority: string; comment?: string }

function stubApi(): Posted[] {
  const posted: Posted[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      let body: unknown = { items: [], total: 0 }
      if (url.includes('/feedback/stats')) body = STATS
      if (init?.method === 'POST' && url.endsWith('/feedback')) {
        // The widget serialises this body itself; only the fields asserted below are read.
        posted.push(JSON.parse(String(init.body)) as Posted)
        body = { id: 'fb-1' }
      }
      return Promise.resolve(
        new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }),
      )
    }),
  )
  return posted
}

function renderWidget() {
  return render(
    <FeedbackProvider apiUrl={API} appName="dashboard">
      <FeedbackWidget />
    </FeedbackProvider>,
  )
}

async function openForm() {
  const user = userEvent.setup()
  await user.keyboard('{Control>}{Shift>}q{/Shift}{/Control}')
  await screen.findByText('Leave Feedback')
  return user
}

function badge(name: RegExp): HTMLElement {
  return screen.getByRole('button', { name })
}

async function submit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Submit Feedback' }))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('feedback form defaults', () => {
  it('submits as a low-priority bug when nothing is chosen', async () => {
    const posted = stubApi()
    renderWidget()
    const user = await openForm()

    await submit(user)

    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0]).toMatchObject({ feedback_type: 'bug', priority: 'low' })
  })
})

describe('feedback form hotkeys', () => {
  it('shows the 1 and 2 key hints on the type and priority badges', async () => {
    stubApi()
    renderWidget()
    await openForm()

    expect(badge(/Bug/)).toHaveAttribute('aria-keyshortcuts', '1')
    expect(badge(/Bug/).querySelector('kbd')).toHaveTextContent('1')
    expect(badge(/Low/)).toHaveAttribute('aria-keyshortcuts', '2')
    expect(badge(/Low/).querySelector('kbd')).toHaveTextContent('2')
  })

  it('1 opens the type list, arrows + Enter pick, and the choice is what gets sent', async () => {
    const posted = stubApi()
    renderWidget()
    const user = await openForm()

    await user.keyboard('1')
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Bug/ })).toHaveFocus()

    await user.keyboard('{ArrowDown}{Enter}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()

    await user.keyboard('2')
    expect(screen.getByRole('option', { name: /Low/ })).toHaveFocus()
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}')

    await submit(user)
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0]).toMatchObject({ feedback_type: 'feature', priority: 'high' })
  })

  it('2 while the type list is open switches to the priority list', async () => {
    stubApi()
    renderWidget()
    const user = await openForm()

    await user.keyboard('1')
    await user.keyboard('2')

    expect(screen.getAllByRole('listbox')).toHaveLength(1)
    expect(screen.getByRole('option', { name: /Low/ })).toHaveFocus()
  })

  it('Escape closes the list without closing the form or changing the value', async () => {
    stubApi()
    renderWidget()
    const user = await openForm()

    await user.keyboard('2{ArrowDown}{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.getByText('Leave Feedback')).toBeInTheDocument()
    expect(badge(/Low/)).toHaveFocus()
  })

  it('typing 1 and 2 in the comment types them and opens nothing', async () => {
    const posted = stubApi()
    renderWidget()
    const user = await openForm()

    const comment = screen.getByPlaceholderText(/Describe the problem/)
    await user.click(comment)
    await user.keyboard('step 1 then 2')

    expect(comment).toHaveValue('step 1 then 2')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()

    await submit(user)
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0]).toMatchObject({ feedback_type: 'bug', priority: 'low', comment: 'step 1 then 2' })
  })

  it('does nothing while the form is closed', async () => {
    stubApi()
    renderWidget()
    const user = userEvent.setup()

    await user.keyboard('12')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.queryByText('Leave Feedback')).not.toBeInTheDocument()
  })
})


/**
 * The package's own stylesheet, as text. Vitest neither applies imported CSS
 * nor serves it through `?raw`, so it is read from disk.
 */
const STYLES = readFileSync(
  resolve(import.meta.dirname, '../../../../../../lib/ui-feedback/packages/ui-feedback-react/src/styles.css'),
  'utf-8',
)

/**
 * Every declaration of `property` in the loaded stylesheets whose rule matches
 * `el`, including rules nested in @media blocks. jsdom's getComputedStyle does
 * not resolve flex properties, so the cascade is read from the CSSOM instead.
 */
function declared(el: Element, property: string): string[] {
  const values: string[] = []
  const walk = (rules: CSSRuleList) => {
    for (const rule of Array.from(rules)) {
      if (rule instanceof CSSMediaRule) walk(rule.cssRules)
      if (rule instanceof CSSStyleRule && el.matches(rule.selectorText)) {
        const value = rule.style.getPropertyValue(property)
        if (value) values.push(value)
      }
    }
  }
  for (const sheet of Array.from(document.styleSheets)) walk(sheet.cssRules)
  return values
}

describe('ticket list filter bar', () => {
  let style: HTMLStyleElement

  beforeEach(() => {
    style = document.createElement('style')
    style.textContent = STYLES
    document.head.appendChild(style)
  })

  afterEach(() => {
    style.remove()
  })

  // Each pill keeps its label on one line (white-space: nowrap); it is the bar
  // that wraps, moving whole pills to the next row.
  it.each([375, 1280])('wraps instead of squashing or scrolling at %ipx', async (width) => {
    stubApi()
    act(() => {
      window.innerWidth = width
      fireEvent(window, new Event('resize'))
    })

    renderWidget()
    const user = userEvent.setup()
    await user.keyboard('{Control>}{Shift>}t{/Shift}{/Control}')
    const all = await screen.findByRole('button', { name: 'All (7)' })
    const bar = all.closest('.ui-feedback-stats-bar')
    if (!bar) throw new Error('filter button is not inside .ui-feedback-stats-bar')

    expect(declared(bar, 'flex-wrap')).toEqual(['wrap'])
    expect(declared(bar, 'flex-shrink')).toEqual(['0'])
    expect(declared(bar, 'overflow-x')).toEqual([])
  })
})
