/**
 * /repos lists every connected repo, not only the registered ones
 * (feedback 29714ff9: "only showing one repo ... we have at least five").
 *
 * The fixture is reached through `fetch`, from the endpoints the page really
 * calls. Five repos are connected: one registered and App-reachable, one
 * registered and assigned to a system, and three the GitHub App was installed
 * on but nobody registered. The old hook built its rows from `/repos` alone and
 * returned two.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useRepoList } from '../useRepoList'

const REGISTERED = [
  { repo_id: 'repo-1', full_name: 'acme/api', system_id: null, is_private: false },
  { repo_id: 'repo-2', full_name: 'acme/web', system_id: 'sys-1', is_private: true },
]
const SYSTEMS = [{ system_id: 'sys-1', name: 'Storefront' }]
const APP_REACHABLE = ['Acme/API', 'acme/worker', 'acme/infra', 'acme/docs']

function stubFetch(lookup: 'complete' | 'partial') {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string) => {
      const path = new URL(input, 'http://test').pathname
      const body = path.endsWith('/github/repos')
        ? {
            repos: APP_REACHABLE.map((full_name, i) => ({
              github_id: i,
              name: full_name.split('/')[1],
              full_name,
              private: full_name === 'acme/infra',
              default_branch: 'main',
              owner: 'acme',
              installation_id: 'inst-1',
            })),
            total: APP_REACHABLE.length,
            lookup,
          }
        : path.endsWith('/systems')
          ? { systems: SYSTEMS, total: SYSTEMS.length }
          : { repos: REGISTERED, total: REGISTERED.length }
      return new Response(JSON.stringify(body), { status: 200 })
    }),
  )
}

async function readyRows() {
  const { result } = renderHook(() => useRepoList())
  await waitFor(() => expect(result.current.kind).toBe('ready'))
  if (result.current.kind !== 'ready') throw new Error('not ready')
  return result.current.repos
}

describe('useRepoList', () => {
  beforeEach(() => stubFetch('complete'))
  afterEach(() => vi.unstubAllGlobals())

  it('lists the union of registered and App-reachable repos, once each', async () => {
    const rows = await readyRows()
    expect(rows.map((r) => r.fullName)).toEqual([
      'acme/api',
      'acme/docs',
      'acme/infra',
      'acme/web',
      'acme/worker',
    ])
  })

  it('marks App-only repos as unregistered and attached, keeping their privacy', async () => {
    const rows = await readyRows()
    const infra = rows.find((r) => r.fullName === 'acme/infra')
    expect(infra).toMatchObject({ registered: false, attachment: 'attached', isPrivate: true, system: null })
    const api = rows.find((r) => r.fullName === 'acme/api')
    expect(api).toMatchObject({ registered: true, attachment: 'attached' })
    const web = rows.find((r) => r.fullName === 'acme/web')
    expect(web).toMatchObject({ registered: true, attachment: 'not-attached', system: 'Storefront' })
  })

  it('still lists App-reachable repos when the App lookup is partial', async () => {
    stubFetch('partial')
    const rows = await readyRows()
    expect(rows).toHaveLength(5)
    expect(rows.find((r) => r.fullName === 'acme/web')?.attachment).toBe('unknown')
  })
})
