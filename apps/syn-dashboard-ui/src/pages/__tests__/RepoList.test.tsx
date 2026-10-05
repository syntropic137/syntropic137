/**
 * The Repos page lists what `/repos` returns, joined to `/systems` for names
 * and to `/github/repos` for whether the GitHub App can reach each one.
 *
 * Served over `fetch` rather than by mocking the hook: the owning system
 * arrives as an id on the repo and as a name on another endpoint, and the join
 * between them is half of what is being asserted.
 *
 * `/github/repos` bodies for a GitHub failure are not written here: they are
 * recorded from the real route by apps/syn-api/tests/test_github_repos_lookup.py,
 * so these tests see what the API actually says when GitHub fails.
 */

import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import githubReposRecorded from '../../../../syn-api/tests/fixtures/github_repos_lookup.json'
import type { RepoSummary, SystemSummary } from '../../api/repos'
import type { components } from '../../generated/api-types'
import { RepoList } from '../RepoList'

function repo(overrides: Partial<RepoSummary> & Pick<RepoSummary, 'repo_id'>): RepoSummary {
  return { organization_id: 'org-1', ...overrides }
}

const SYSTEMS: SystemSummary[] = [{ system_id: 'sys-7', organization_id: 'org-1', name: 'Billing' }]

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** What `/github/repos` returns for a repo the App can reach. */
function appRepo(fullName: string) {
  const [owner, name] = fullName.split('/')
  return {
    github_id: 1,
    name,
    full_name: fullName,
    private: false,
    default_branch: 'main',
    owner,
    installation_id: 'inst-42',
  }
}

type GitHubRepoList = components['schemas']['GitHubRepoListResponse']

// Safe: the file is written from GitHubRepoListResponse by the API test, which
// fails if it no longer matches what the route returns.
const recorded = githubReposRecorded as Record<keyof typeof githubReposRecorded, GitHubRepoList>

function githubRepos(appAccess: string[] | GitHubRepoList | null): Response {
  if (appAccess === null) return new Response('{"detail":"no app"}', { status: 502 })
  if (!Array.isArray(appAccess)) return json(appAccess)
  return json({
    repos: appAccess.map(appRepo),
    total: appAccess.length,
    installation_id: null,
    lookup: 'complete',
  })
}

/**
 * `appAccess` names the repos a complete lookup found. null makes the request
 * itself fail, as it does with no App configured; a recorded body is served as is.
 */
function serve(repos: RepoSummary[], appAccess: string[] | GitHubRepoList | null = []) {
  vi.stubGlobal('fetch', async (input: RequestInfo | URL): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (url.endsWith('/api/v1/repos')) return json({ repos, total: repos.length })
    if (url.endsWith('/api/v1/systems')) return json({ systems: SYSTEMS, total: SYSTEMS.length })
    if (url.endsWith('/api/v1/github/repos')) return githubRepos(appAccess)
    throw new Error(`No fake endpoint for ${url}`)
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderPage() {
  return render(
    <MemoryRouter>
      <RepoList />
    </MemoryRouter>,
  )
}

/** The rendered row for a repo. Throws if the page has none. */
async function rowFor(fullName: string): Promise<HTMLElement> {
  const row = (await screen.findByText(fullName)).closest('tr')
  if (!row) throw new Error(`No row for ${fullName}`)
  return row
}

describe('Repos page', () => {
  it('shows each repo with its system by name and whether it is attached', async () => {
    serve([
      repo({
        repo_id: 'r1',
        full_name: 'acme/payments',
        system_id: 'sys-7',
        installation_id: 'inst-42',
      }),
      repo({ repo_id: 'r2', full_name: 'acme/scratch', system_id: '', installation_id: '' }),
    ], ['acme/payments'])
    renderPage()

    const attached = within(await rowFor('acme/payments'))
    expect(attached.getByText('Billing')).toBeInTheDocument()
    expect(attached.queryByText('sys-7')).not.toBeInTheDocument()
    expect(attached.getByText('Attached')).toBeInTheDocument()

    const loose = within(await rowFor('acme/scratch'))
    expect(loose.getByText('None')).toBeInTheDocument()
    expect(loose.getByText('Not attached')).toBeInTheDocument()
  })

  // `syn repo register` sends `installation_id: ""`, and installing the App
  // later updates the installation projection, never the repo. So a repo the
  // App can reach still carries an empty `installation_id` here.
  it('shows a CLI-registered repo as attached once the App can reach it', async () => {
    const registered = repo({ repo_id: 'r4', full_name: 'acme/api', installation_id: '' })

    serve([registered], [])
    const before = renderPage()
    expect(within(await rowFor('acme/api')).getByText('Not attached')).toBeInTheDocument()
    before.unmount()

    serve([registered], ['Acme/API'])
    renderPage()
    expect(within(await rowFor('acme/api')).getByText('Attached')).toBeInTheDocument()
  })

  it('shows a repo as not attached once the App loses access to it', async () => {
    // The repo still remembers the installation it was registered under.
    const registered = repo({ repo_id: 'r5', full_name: 'acme/old', installation_id: 'inst-42' })

    serve([registered], ['acme/old'])
    const before = renderPage()
    expect(within(await rowFor('acme/old')).getByText('Attached')).toBeInTheDocument()
    before.unmount()

    serve([registered], [])
    renderPage()
    expect(within(await rowFor('acme/old')).getByText('Not attached')).toBeInTheDocument()
  })

  it('says unknown, not detached, when App access cannot be looked up', async () => {
    serve([repo({ repo_id: 'r6', full_name: 'acme/web', installation_id: 'inst-42' })], null)
    renderPage()

    const row = within(await rowFor('acme/web'))
    expect(row.getByText('Unknown')).toBeInTheDocument()
    expect(row.queryByText('Not attached')).not.toBeInTheDocument()
  })

  // The API answers 200 here; only its `lookup` says GitHub failed.
  it('says unknown when GitHub failed the installation lookup, not detached', async () => {
    serve(
      [repo({ repo_id: 'r7', full_name: 'acme/payments', installation_id: '' })],
      recorded.installation_lookup_failed,
    )
    renderPage()

    const row = within(await rowFor('acme/payments'))
    expect(row.getByText('Unknown')).toBeInTheDocument()
    expect(row.queryByText('Not attached')).not.toBeInTheDocument()
  })

  // GitHub listed the installation but saving it failed, so it was never asked.
  it('says unknown when an installation could not be saved, not detached', async () => {
    serve(
      [repo({ repo_id: 'r7', full_name: 'acme/payments', installation_id: '' })],
      recorded.installation_not_persisted,
    )
    renderPage()

    const row = within(await rowFor('acme/payments'))
    expect(row.getByText('Unknown')).toBeInTheDocument()
    expect(row.queryByText('Not attached')).not.toBeInTheDocument()
  })

  it('says not attached when GitHub confirmed the App reaches nothing', async () => {
    serve(
      [repo({ repo_id: 'r7', full_name: 'acme/payments', installation_id: '' })],
      recorded.confirmed_empty,
    )
    renderPage()

    expect(within(await rowFor('acme/payments')).getByText('Not attached')).toBeInTheDocument()
  })

  it('keeps what a partial lookup found and leaves the rest unknown', async () => {
    serve(
      [
        repo({ repo_id: 'r7', full_name: 'acme/payments', installation_id: '' }),
        repo({ repo_id: 'r8', full_name: 'acme/web', installation_id: '' }),
      ],
      recorded.one_installation_failed,
    )
    renderPage()

    expect(within(await rowFor('acme/payments')).getByText('Attached')).toBeInTheDocument()
    expect(within(await rowFor('acme/web')).getByText('Unknown')).toBeInTheDocument()
  })

  it('falls back to the system id when the system is not listed', async () => {
    serve([repo({ repo_id: 'r3', full_name: 'acme/legacy', system_id: 'sys-gone' })])
    renderPage()

    expect(within(await rowFor('acme/legacy')).getByText('sys-gone')).toBeInTheDocument()
  })

  it('says how to attach one when there are none', async () => {
    serve([])
    renderPage()

    expect(await screen.findByText('No repositories attached')).toBeInTheDocument()
    expect(screen.getByText(/syn repo register --url owner\/repo/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
