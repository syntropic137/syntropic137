/**
 * The Repos page lists what `/repos` returns, joined to `/systems` for names
 * and to `/github/repos` for whether the GitHub App can reach each one.
 *
 * Served over `fetch` rather than by mocking the hook: the owning system
 * arrives as an id on the repo and as a name on another endpoint, and the join
 * between them is half of what is being asserted.
 */

import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { RepoSummary, SystemSummary } from '../../api/repos'
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

/** `appAccess` null makes the App lookup fail, as it does with no App configured. */
function serve(repos: RepoSummary[], appAccess: string[] | null = []) {
  vi.stubGlobal('fetch', async (input: RequestInfo | URL): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (url.endsWith('/api/v1/repos')) return json({ repos, total: repos.length })
    if (url.endsWith('/api/v1/systems')) return json({ systems: SYSTEMS, total: SYSTEMS.length })
    if (url.endsWith('/api/v1/github/repos')) {
      if (appAccess === null) return new Response('{"detail":"no app"}', { status: 502 })
      return json({ repos: appAccess.map(appRepo), total: appAccess.length })
    }
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
