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
 *    repo, so a private repo rendered as public. For a repo the App does not
 *    reach, that same stored false is unknown privacy, not public.
 * 3. Rows are keyed by `repo_id`, the Repo aggregate's own identity, never by
 *    name. Two organizations that each registered `acme/api`, a Gitea
 *    `acme/worker` beside a GitHub one, and `ACME/web` beside `acme/web` in
 *    one organization, used to collapse into one row - losing a row, its
 *    System, and labelling a non-GitHub repo "Attached". Repo uniqueness is
 *    claimed on `(organization_id, provider, full_name)` with no case folding
 *    (`aggregate_repo_claim/claim_id.py`), so case-variant names are two
 *    Repos and the page owes them two rows.
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
  // Same organization and provider as repo-2, differing only in case. The
  // repo claim does not fold case, so this is a second Repo, not the same one.
  {
    repo_id: 'repo-5',
    organization_id: 'org-a',
    provider: 'github',
    full_name: 'ACME/web',
    system_id: 'sys-2',
    is_private: false,
  },
  // Stored private, but GitHub says public now.
  {
    repo_id: 'repo-6',
    organization_id: 'org-a',
    provider: 'github',
    full_name: 'acme/docs',
    system_id: null,
    is_private: true,
  },
  // Registered by an older client that stored no privacy at all.
  {
    repo_id: 'repo-7',
    organization_id: 'org-a',
    provider: 'github',
    full_name: 'acme/legacy',
    system_id: null,
  },
]
const SYSTEMS = [
  { system_id: 'sys-1', name: 'Storefront' },
  { system_id: 'sys-2', name: 'Checkout' },
]
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
    // Lower-cased because `localeCompare` decides where `ACME/web` falls
    // relative to `acme/web`, and that ordering is not what is under test.
    expect(rows.map((r) => r.fullName.toLowerCase())).toEqual([
      'acme/api',
      'acme/api',
      'acme/docs',
      'acme/infra',
      'acme/legacy',
      'acme/web',
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
      privacy: 'private',
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
      expect(row).toMatchObject({ registered: true, attachment: 'attached', privacy: 'private' })
    }
  })

  it('shows public when the App reports a registered repo as public', async () => {
    const rows = await readyRows()
    // Stored true, public on GitHub: the live answer wins in both directions.
    const worker = rows.find((r) => r.key === 'repo-6')
    expect(worker).toMatchObject({ registered: true, attachment: 'attached', privacy: 'public' })
  })

  it('keeps a stored private for a registered repo the App does not reach', async () => {
    const rows = await readyRows()
    expect(rows.find((r) => r.key === 'repo-2')?.privacy).toBe('private')
  })

  it('calls a stored false unknown, not public, when the App does not reach the repo', async () => {
    const rows = await readyRows()
    // `syn repo register` stores false for every repo, so it says nothing.
    expect(rows.find((r) => r.key === 'repo-5')?.privacy).toBe('unknown')
    expect(rows.find((r) => r.key === 'repo-7')?.privacy).toBe('unknown')
  })

  it('keeps one row per organization that registered the same name', async () => {
    const rows = await readyRows()
    const keys = rows.filter((r) => r.fullName === 'acme/api').map((r) => r.key)
    expect(keys).toEqual(['repo-1', 'repo-3'])
  })

  it('keeps both repos when one organization registered two spellings of a name', async () => {
    const rows = await readyRows()
    // Two Repos: the claim on (organization_id, provider, full_name) folds no
    // case, so both registrations succeeded and both own a System.
    const byKey = new Map(rows.map((r) => [r.key, r]))
    expect(byKey.get('repo-2')).toMatchObject({ fullName: 'acme/web', system: 'Storefront' })
    expect(byKey.get('repo-5')).toMatchObject({ fullName: 'ACME/web', system: 'Checkout' })
  })

  it('never attaches a non-GitHub repo that shares a name with an App repo', async () => {
    const rows = await readyRows()
    const workers = rows.filter((r) => r.fullName === 'acme/worker')
    // The Gitea repo and the App's GitHub repo are two connected repos.
    expect(workers).toHaveLength(2)
    const gitea = workers.find((r) => r.key === 'repo-4')
    expect(gitea).toMatchObject({ registered: true, attachment: 'not-attached', privacy: 'private' })
    expect(workers.find((r) => !r.registered)).toMatchObject({ attachment: 'attached' })
  })

  it('still lists App-reachable repos when the App lookup is partial', async () => {
    stubFetch('partial')
    const rows = await readyRows()
    expect(rows).toHaveLength(9)
    expect(rows.find((r) => r.fullName === 'acme/web')?.attachment).toBe('unknown')
    // A partial GitHub lookup says nothing about a Gitea repo.
    expect(rows.find((r) => r.key === 'repo-4')?.attachment).toBe('not-attached')
  })
})
