/**
 * The executions list on a phone keeps a long repo list inside its card
 * (feedback fc9f69a0, 5f2359cd, both at 411x780).
 *
 * The card's metrics sit in a two-column grid, and a grid item is never
 * narrower than its content. A repo list with no break opportunity therefore
 * set its column's width: it ran into the Tokens value beside it
 * ("syntropic137/syntropic137.1M"), or wrapped one hyphen-segment per line into
 * a column too narrow to read.
 *
 * jsdom does no layout, so `scrollWidth` here is always 0 and cannot show the
 * overflow; the 411px screenshots on the PR are the visual evidence. What this
 * pins is the layout contract that prevents it, read off the page an operator
 * gets on a phone rather than off the card in isolation: the page must choose
 * the card list, and the repo value must be a shrinkable, full-row,
 * single-line cell whose full text is still reachable.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'

import { serveListEndpoint } from '../../../test/fakeListServer'
import { EXECUTIONS, matchesExecutionSearch } from '../../../test/listFixtures'
import { ExecutionList } from '../ExecutionList'

vi.mock('../../../hooks/useActivityStream', () => ({
  useActivityStream: vi.fn(() => ({ connected: true, lastEventAt: null })),
}))

/**
 * A repository slug `RepositoryRef.parse` accepts, with no break opportunity in
 * its name, beside a second repo. Verification measured this shape scrolling
 * the detail page to 483px at 411px.
 */
const LONG_REPO = `syntropic137/${'r'.repeat(90)}`
const REPOS = [LONG_REPO, 'syntropic137/event-sourcing-platform']

/**
 * `repos_display` exactly as the API builds it: `format_repos`
 * (syn_shared/display/formatters.py) gives the first repo's name and `+N`.
 */
const LONG_REPOS = `${'r'.repeat(90)} +1`

serveListEndpoint({
  path: '/api/v1/executions',
  collection: [
    { ...EXECUTIONS[0], repos: REPOS, repos_display: LONG_REPOS },
    ...EXECUTIONS.slice(1),
  ],
  matchesSearch: matchesExecutionSearch,
})

/** A 411px viewport: every `min-width` query fails, as it does on the phone. */
let desktopMatchMedia: typeof window.matchMedia
beforeAll(() => {
  desktopMatchMedia = window.matchMedia
  window.matchMedia = (query: string) => ({ ...desktopMatchMedia(query), matches: false })
})
afterAll(() => {
  window.matchMedia = desktopMatchMedia
})

describe('executions list at a phone width', () => {
  it('renders cards, not the desktop table', async () => {
    render(
      <MemoryRouter initialEntries={['/executions']}>
        <ExecutionList />
      </MemoryRouter>,
    )
    await screen.findByTitle(LONG_REPOS)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('keeps a long repo list on one line in a cell that can shrink to the card', async () => {
    render(
      <MemoryRouter initialEntries={['/executions']}>
        <ExecutionList />
      </MemoryRouter>,
    )
    const value = await screen.findByTitle(LONG_REPOS)
    expect(value).toHaveTextContent(LONG_REPOS)
    // One clipped line, not a column of hyphen-segments.
    expect(value).toHaveClass('truncate')
    const cell = value.parentElement
    // Without min-w-0 a grid item's floor is its content width.
    expect(cell).toHaveClass('min-w-0')
    // Its own row, so the Tokens value is never beside it.
    expect(cell).toHaveClass('col-span-full')
  })
})
