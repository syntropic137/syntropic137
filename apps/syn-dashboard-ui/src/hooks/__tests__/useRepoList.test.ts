/**
 * /repos lists every connected repo, not only the registered ones
 * (feedback 29714ff9: "only showing one repo ... we have at least five").
 *
 * The fixture is reached through `fetch`, from the endpoints the page really
 * calls. It covers the three things the rows have to get right:
 *
 * 1. The union of `/repos` and `/github/repos` - the old hook built its rows
 *    from `/repos` alone.
 * 2. Privacy for a repo the App reaches comes from the App, not from the
 *    stored flag: `syn repo register` sends `is_private: false` for every
 *    repo, so a private repo rendered as public.
 * 3. Rows are keyed by a Repo's domain identity,
 *    `(organization_id, provider, full_name)`. Two organizations that each
 *    registered `acme/api`, and a Gitea `acme/worker` beside a GitHub one,
 *    used to collapse into one row - losing a row, its System, and labelling a
 *    non-GitHub repo "Attached".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useRepoList } from '../useRepoList'

const REGISTERED = [
  {
    repo_id: 'repo-1',
    organization_id: 'org-a',
    provider: 'github',
    full_name: 'acme/api',
    system_id: null,
    // What `syn repo register` stores for every repo, private or not.
    is_private: false,
  },
  {
    repo_id: 'repo-2',
    organization_id: 'org-a',
    provider: 'github',
    full_name: 'acme/web',
    system_id: 'sys-1',
    is_private: true,
  },
  // A second organization registered the same name.
  {
    repo_id: 'repo-3',
    organization_id: 'org-b',
    provider: 'github',
    full_name: 'acme/api',
    system_id: null,
    is_private: false,
  },
  // Same name as a repo the GitHub App reaches, but on another provider.
  {
    repo_id: 'repo-4',
    organization_id: 'org-a',
    provider: 'gitea',
    full_name: 'acme/worker',
    system_id: null,
    is_private: true,
  },
]
const SYSTEMS = [{ system_id: 'sys-1', name: 'Storefront' }]
const APP_REACHABLE = ['Acme/API', 'acme/worker', 'acme/infra', 'acme/docs']
/** What GitHub reports as private right now, lower-cased. */
const PRIVATE_IN_APP = new Set(['acme/api', 'acme/infra'])

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
              private: PRIVATE_IN_APP.has(full_name.toLowerCase()),
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

  it('lists the union of registered and App-reachable repos', async () => {
    const rows = await readyRows()
    expect(rows.map((r) => r.fullName)).toEqual([
      'acme/api',
      'acme/api',
      'acme/docs',
      'acme/infra',
      'acme/web',
      'acme/worker',
      'acme/worker',
    ])
  })

  it('marks App-only repos as unregistered and attached, keeping their privacy', async () => {
    const rows = await readyRows()
    const infra = rows.find((r) => r.fullName === 'acme/infra')
    expect(infra).toMatchObject({
      registered: false,
      attachment: 'attached',
      isPrivate: true,
      system: null,
    })
    const web = rows.find((r) => r.fullName === 'acme/web')
    expect(web).toMatchObject({ registered: true, attachment: 'not-attached', system: 'Storefront' })
  })

  it('shows the privacy the App reports, not the one registration stored', async () => {
    const rows = await readyRows()
    // Stored false (hardcoded by `syn repo register`), private on GitHub.
    const api = rows.filter((r) => r.fullName === 'acme/api')
    expect(api).toHaveLength(2)
    for (const row of api) {
      expect(row).toMatchObject({ registered: true, attachment: 'attached', isPrivate: true })
    }
  })

  it('keeps the stored privacy for a registered repo the App does not reach', async () => {
    const rows = await readyRows()
    expect(rows.find((r) => r.fullName === 'acme/web')?.isPrivate).toBe(true)
  })

  it('keeps one row per organization that registered the same name', async () => {
    const rows = await readyRows()
    const keys = rows.filter((r) => r.fullName === 'acme/api').map((r) => r.key)
    expect(keys).toEqual(['org-a|github|acme/api', 'org-b|github|acme/api'])
  })

  it('never attaches a non-GitHub repo that shares a name with an App repo', async () => {
    const rows = await readyRows()
    const workers = rows.filter((r) => r.fullName === 'acme/worker')
    // The Gitea repo and the App's GitHub repo are two connected repos.
    expect(workers).toHaveLength(2)
    const gitea = workers.find((r) => r.key === 'org-a|gitea|acme/worker')
    expect(gitea).toMatchObject({ registered: true, attachment: 'not-attached', isPrivate: true })
    expect(workers.find((r) => !r.registered)).toMatchObject({ attachment: 'attached' })
  })

  it('still lists App-reachable repos when the App lookup is partial', async () => {
    stubFetch('partial')
    const rows = await readyRows()
    expect(rows).toHaveLength(7)
    expect(rows.find((r) => r.fullName === 'acme/web')?.attachment).toBe('unknown')
    // A partial GitHub lookup says nothing about a Gitea repo.
    expect(rows.find((r) => r.key === 'org-a|gitea|acme/worker')?.attachment).toBe('not-attached')
  })
})
