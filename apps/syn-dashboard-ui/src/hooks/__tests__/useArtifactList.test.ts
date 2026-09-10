/**
 * The artifacts list, against a server that really filters, tallies and pages.
 *
 * This hook is the #1159 shape on a third surface. It used to fetch
 * `limit: 100` once and narrow the result in the browser, so the type
 * dropdown, the search box and the row count all described the newest 100
 * artifacts rather than the collection - and until #1204 the endpoint could
 * not answer any other way.
 *
 * Artifacts spell the shared contract differently, which is the part most
 * likely to be got wrong twice: the window bounds `created_after` rather than
 * `started_after`, and the facet is `artifact_type` tallied under
 * `type_counts`. Both are on the wire here, not just in the hook's arguments.
 *
 * As with executions, all of it rests on a fixture of 120 rows - three pages.
 * See `src/test/listFixtures.ts` for why nothing smaller can fail.
 */

import { describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'

import { ARTIFACT_DIALECT, serveListEndpoint } from '../../test/fakeListServer'
import { ARTIFACTS, DAY_MS, matchesArtifactSearch, tally, within } from '../../test/listFixtures'
import { LIST_PAGE_SIZE } from '../useServerList'
import { useArtifactList } from '../useArtifactList'

vi.mock('../useActivityStream', () => ({
  useActivityStream: vi.fn(() => ({ connected: true, lastEventAt: null })),
}))

const server = serveListEndpoint({
  path: '/api/v1/artifacts',
  collection: ARTIFACTS,
  matchesSearch: matchesArtifactSearch,
  dialect: ARTIFACT_DIALECT,
})

const TOTAL = ARTIFACTS.length
const createdAt = (row: { created_at: string }) => row.created_at
const IN_7D = within(ARTIFACTS, 7 * DAY_MS, createdAt).length
const TYPE_COUNTS = tally(ARTIFACTS, (row) => row.artifact_type)
const DELIVERABLES = TYPE_COUNTS.deliverable

function wrapperAt(url: string) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return createElement(MemoryRouter, { initialEntries: [url] }, children)
  }
}

/** The ids the server should have put on page `page` of the whole collection. */
function idsOnPage(page: number): string[] {
  const offset = (page - 1) * LIST_PAGE_SIZE
  return ARTIFACTS.slice(offset, offset + LIST_PAGE_SIZE).map((a) => a.id)
}

function renderList(url = '/artifacts?timeWindow=all') {
  const rendered = renderHook(() => useArtifactList(), { wrapper: wrapperAt(url) })
  const ids = () => rendered.result.current.artifacts.map((a) => a.id)
  return { ...rendered, ids }
}

describe('useArtifactList', () => {
  it('is the fixture the regression needs: more than one page, in both windows', () => {
    expect(TOTAL).toBeGreaterThan(LIST_PAGE_SIZE * 2)
    expect(IN_7D).toBeGreaterThan(LIST_PAGE_SIZE)
    expect(TOTAL).toBeGreaterThan(IN_7D)
    expect(DELIVERABLES).toBeGreaterThan(LIST_PAGE_SIZE)
  })

  it('reports the collection total, not the number of rows on the page', async () => {
    const { result, ids } = renderList()

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.total).toBe(TOTAL)
    expect(result.current.artifacts).toHaveLength(LIST_PAGE_SIZE)
    expect(result.current.total).not.toBe(result.current.artifacts.length)
    expect(result.current.pageSize).toBe(LIST_PAGE_SIZE)
    expect(result.current.totalPages).toBe(3)
    expect(ids()).toEqual(idsOnPage(1))
  })

  it('bounds the window on when an artifact was created, not started', async () => {
    const { result } = renderList('/artifacts?timeWindow=7d')

    await waitFor(() => expect(result.current.loading).toBe(false))

    // An artifact is never "started". Sending `started_after` would be a 422,
    // and a bound with no offset is a 422 too (#1183).
    expect(server.lastRequest.params.get('created_after')).toMatch(/(Z|[+-]\d{2}:\d{2})$/)
    expect(server.lastRequest.params.has('started_after')).toBe(false)
    expect(result.current.total).toBe(IN_7D)
  })

  it('holds the total steady while paging, as the rows beneath it change', async () => {
    const { result, ids } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))

    const seenTotals = [result.current.total]
    const seenRowCounts = [result.current.artifacts.length]

    for (const page of [2, 3]) {
      act(() => result.current.setPage(page))
      await waitFor(() => expect(ids()).toEqual(idsOnPage(page)))
      seenTotals.push(result.current.total)
      seenRowCounts.push(result.current.artifacts.length)
    }

    // `page_size` is fixed at `LIST_PAGE_SIZE` by `useListQuery` and is not a
    // parameter this hook exposes; varying the page is the same property.
    // A total taken from the rows in hand would have read 50, 50, 20.
    expect(seenTotals).toEqual([TOTAL, TOTAL, TOTAL])
    expect(seenRowCounts).toEqual([LIST_PAGE_SIZE, LIST_PAGE_SIZE, TOTAL - 2 * LIST_PAGE_SIZE])
  })

  it('page 2 holds different artifacts, and is not empty', async () => {
    const { result, ids } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))
    const firstPage = ids()

    act(() => result.current.setPage(2))
    await waitFor(() => expect(server.lastRequest.params.get('page')).toBe('2'))
    await waitFor(() => expect(ids()).toEqual(idsOnPage(2)))

    expect(ids()).toHaveLength(LIST_PAGE_SIZE)
    expect(ids()).not.toEqual(firstPage)
    expect(firstPage.some((id) => ids().includes(id))).toBe(false)
  })

  it('paging reaches the last page, and the arithmetic closes on the total', async () => {
    const { result, ids } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))

    for (const page of [2, 3]) {
      act(() => result.current.setPage(page))
      await waitFor(() => expect(ids()).toEqual(idsOnPage(page)))
    }

    const lastPageRows = result.current.artifacts.length
    expect(result.current.page).toBe(3)
    expect((result.current.totalPages - 1) * result.current.pageSize + lastPageRows).toBe(TOTAL)
    expect(ids()).toContain(ARTIFACTS[TOTAL - 1].id)
  })

  it('widening the time window changes the total, though page 1 may not move', async () => {
    const { result, ids } = renderList('/artifacts?timeWindow=7d')
    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.total).toBe(IN_7D)
    const firstPageUnder7d = ids()

    act(() => result.current.setTimeWindow('all'))
    await waitFor(() => expect(result.current.total).toBe(TOTAL))

    // Not an assertion that the rows changed: both windows hold more than a
    // page, so the newest 50 are the same 50 and must be expected to be.
    expect(ids()).toEqual(firstPageUnder7d)
    expect(server.lastRequest.params.has('created_after')).toBe(false)
  })

  it('takes the type counts from the server, over the collection', async () => {
    const { result } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))

    // Counted over 120 rows while 50 are in hand.
    expect(result.current.typeCounts).toEqual(TYPE_COUNTS)
    expect(result.current.typeCounts.deliverable).toBeGreaterThan(LIST_PAGE_SIZE)
    // The shared hook calls its facet counts `statusCounts`; artifacts have no
    // status, and this is the same tally under the name the page reads.
    expect(result.current.statusCounts).toEqual(TYPE_COUNTS)
  })

  it('filters by type on the server, and still reports every type', async () => {
    const { result } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => result.current.setTypeFilter('log'))
    await waitFor(() => expect(result.current.total).toBe(TYPE_COUNTS.log))

    expect(server.lastRequest.params.get('artifact_type')).toBe('log')
    // Selecting a type narrows the rows, not the tally.
    expect(result.current.typeCounts).toEqual(TYPE_COUNTS)
    expect(result.current.typeCounts.deliverable).toBe(DELIVERABLES)
  })

  it('a type filter is a different collection, so it is asked for from page 1', async () => {
    const { result, ids } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => result.current.setPage(3))
    await waitFor(() => expect(ids()).toEqual(idsOnPage(3)))

    act(() => result.current.setTypeFilter('deliverable'))
    await waitFor(() => expect(result.current.total).toBe(DELIVERABLES))

    // The type narrowing is invisible to `useListQuery`, which is why this
    // hook passes it as a scope key. Page 3 of 24 logs would be empty.
    expect(result.current.page).toBe(1)
    expect(server.lastRequest.params.get('page')).toBe('1')
    expect(result.current.artifacts).toHaveLength(LIST_PAGE_SIZE)
  })

  it('sends the search term to the server rather than narrowing the page', async () => {
    const { result } = renderList()
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => result.current.setSearchQuery('Artifact 119'))

    // The oldest artifact, three pages from the one in hand.
    await waitFor(() => expect(server.lastRequest.params.get('q')).toBe('Artifact 119'))
    await waitFor(() => expect(result.current.total).toBe(1))
    expect(result.current.artifacts.map((a) => a.id)).toEqual([ARTIFACTS[TOTAL - 1].id])
  })
})

/**
 * A quarter of the real corpus carries `created_at: null` (#1215), so a window
 * silently dropped 274 of 1037 artifacts and the count said only "755". The
 * server now reports how many it could not judge; this covers the hop that
 * carries the number from the response into the hook, which is exactly where a
 * value gets written correctly and then dropped.
 *
 * Its own fixture: the shared 120 are all dated on purpose, and the counts
 * every other test asserts are derived from them.
 */
describe('useArtifactList with undated rows', () => {
  const DATED = ARTIFACTS.slice(0, 4)
  const UNDATED = [0, 1, 2].map((i) => ({ ...ARTIFACTS[10 + i], created_at: '' }))

  const mixedServer = serveListEndpoint({
    path: '/api/v1/artifacts',
    collection: [...DATED, ...UNDATED],
    matchesSearch: matchesArtifactSearch,
    dialect: ARTIFACT_DIALECT,
  })

  it('carries the count of rows the window could not judge', async () => {
    const { result } = renderList('/artifacts?timeWindow=7d')

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(mixedServer.lastRequest.params.has('created_after')).toBe(true)
    expect(result.current.total).toBe(DATED.length)
    expect(result.current.excludedUndated).toBe(UNDATED.length)
  })

  it('excludes nothing, and returns the undated rows, when no window is set', async () => {
    const { result } = renderList('/artifacts?timeWindow=all')

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.total).toBe(DATED.length + UNDATED.length)
    expect(result.current.excludedUndated).toBe(0)
  })
})
