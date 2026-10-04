/**
 * The Repos page lists what `/repos` returns, joined to `/systems` for names.
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

function serve(repos: RepoSummary[]) {
  vi.stubGlobal('fetch', async (input: RequestInfo | URL): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (url.endsWith('/api/v1/repos')) return json({ repos, total: repos.length })
    if (url.endsWith('/api/v1/systems')) return json({ systems: SYSTEMS, total: SYSTEMS.length })
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
    ])
    renderPage()

    const attached = within(await rowFor('acme/payments'))
    expect(attached.getByText('Billing')).toBeInTheDocument()
    expect(attached.queryByText('sys-7')).not.toBeInTheDocument()
    expect(attached.getByText('Attached')).toBeInTheDocument()

    const loose = within(await rowFor('acme/scratch'))
    expect(loose.getByText('None')).toBeInTheDocument()
    expect(loose.getByText('Not attached')).toBeInTheDocument()
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
