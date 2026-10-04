/**
 * Workflow search reaches the server and searches the whole collection.
 *
 * The bug: the hook filtered the page it had already fetched, so a workflow on
 * page 3 could not be found from page 1. The stub below is reached through
 * `fetch` and honours the `search` it is sent, so a hook that drops the term
 * (or filters locally again) gets the unfiltered first page back and fails.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useWorkflowList } from '../useWorkflowList'

const ALL = Array.from({ length: 45 }, (_, i) => ({
  id: `wf-${String(i).padStart(2, '0')}`,
  name: i === 44 ? 'Needle Release Train' : `Workflow ${i}`,
  workflow_type: 'custom',
  phase_count: 1,
  created_at: null,
  runs_count: 0,
  is_archived: false,
  requires_repos: false,
  tags: [],
}))

let requests: URL[] = []

beforeEach(() => {
  requests = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string) => {
      const url = new URL(input, 'http://test')
      requests.push(url)
      const term = (url.searchParams.get('search') ?? '').toLowerCase()
      const page = Number(url.searchParams.get('page') ?? 1)
      const size = Number(url.searchParams.get('page_size') ?? 20)
      const matched = ALL.filter(
        (w) => w.name.toLowerCase().includes(term) || w.id.toLowerCase().includes(term),
      )
      const body = {
        workflows: matched.slice((page - 1) * size, page * size),
        total: matched.length,
        page,
        page_size: size,
      }
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('useWorkflowList search', () => {
  it('sends the search to the API and finds a workflow beyond the first page', async () => {
    const { result } = renderHook(() => useWorkflowList())
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.workflows.map((w) => w.id)).not.toContain('wf-44')

    act(() => result.current.setSearchQuery('needle'))

    await waitFor(() => expect(result.current.workflows.map((w) => w.id)).toEqual(['wf-44']))
    expect(result.current.total).toBe(1)
    expect(requests.at(-1)?.searchParams.get('search')).toBe('needle')
  })

  it('debounces typing into a single search request', async () => {
    const { result } = renderHook(() => useWorkflowList())
    await waitFor(() => expect(result.current.loading).toBe(false))
    const before = requests.length

    act(() => {
      result.current.setSearchQuery('n')
      result.current.setSearchQuery('ne')
      result.current.setSearchQuery('needle')
    })

    await waitFor(() => expect(result.current.total).toBe(1))
    const searched = requests.slice(before).map((u) => u.searchParams.get('search'))
    expect(searched).toEqual(['needle'])
  })

  it('returns to page 1 when the search changes', async () => {
    const { result } = renderHook(() => useWorkflowList())
    await waitFor(() => expect(result.current.loading).toBe(false))

    act(() => result.current.setPage(3))
    await waitFor(() => expect(requests.at(-1)?.searchParams.get('page')).toBe('3'))

    act(() => result.current.setSearchQuery('workflow'))

    await waitFor(() => expect(requests.at(-1)?.searchParams.get('search')).toBe('workflow'))
    expect(result.current.page).toBe(1)
    expect(requests.at(-1)?.searchParams.get('page')).toBe('1')
  })
})
