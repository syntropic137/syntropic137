/**
 * Binary artifacts are shown and downloaded from their bytes (#1787).
 *
 * The JSON detail carries no `content` for a binary type (#990): the bytes are
 * served by `/raw`. Before this, a screenshot read "Content not available" and
 * Download returned early without doing anything. Each case renders the whole
 * page over a faked `fetch`, so the API answer, the page and the header are
 * all on the path.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { components } from '../../generated/api-types'
import { ArtifactDetail } from '../ArtifactDetail'

type ApiArtifact = components['schemas']['ArtifactResponse']

/** An id that changes under `encodeURIComponent`, so an unencoded URL fails. */
const ID = 'art 1'
const RAW_URL = '/api/v1/artifacts/art%201/raw'

function artifact(overrides: Partial<ApiArtifact>): ApiArtifact {
  return {
    id: ID,
    workflow_id: null,
    phase_id: null,
    session_id: null,
    artifact_type: 'other',
    is_primary_deliverable: true,
    content: null,
    content_type: 'text/plain',
    content_hash: 'abc123',
    size_bytes: 42,
    title: 'screenshot.png',
    derived_from: [],
    created_at: '2026-11-01T00:00:00Z',
    created_by: null,
    metadata: {},
    ...overrides,
  }
}

let served: ApiArtifact

beforeEach(() => {
  vi.stubGlobal('fetch', async (input: RequestInfo | URL): Promise<Response> => {
    const url = new URL(
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
      'http://dashboard',
    )
    if (decodeURIComponent(url.pathname) !== `/api/v1/artifacts/${ID}`) throw new Error(`No fake endpoint for ${url}`)
    return new Response(JSON.stringify(served), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/artifacts/${encodeURIComponent(ID)}`]}>
      <Routes>
        <Route path="/artifacts/:artifactId" element={<ArtifactDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ArtifactDetail with a binary artifact', () => {
  it('shows a PNG from its raw bytes, with no text body', async () => {
    served = artifact({ content_type: 'image/png', artifact_type: 'image' })
    const { container } = renderPage()

    const img = await screen.findByRole('img', { name: 'screenshot.png' })
    expect(img).toHaveAttribute('src', RAW_URL)
    expect(container.querySelector('pre')).toBeNull()
    expect(screen.queryByText('Content not available for preview')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download' })).toHaveAttribute('href', RAW_URL)
  })

  it('offers a PDF for download from its raw bytes, with no preview', async () => {
    served = artifact({ content_type: 'application/pdf', title: 'report.pdf' })
    const { container } = renderPage()

    const download = await screen.findByRole('link', { name: 'Download' })
    expect(download).toHaveAttribute('href', RAW_URL)
    expect(download).toHaveAttribute('download', 'report.pdf')
    expect(screen.getByText(/No preview for application\/pdf/)).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('pre')).toBeNull()
  })
})

describe('ArtifactDetail with a text artifact', () => {
  it('renders markdown as before, downloaded from its content', async () => {
    served = artifact({
      content_type: 'text/markdown',
      artifact_type: 'markdown',
      title: 'notes.md',
      content: '# Findings\n\nAll green.',
    })
    const { container } = renderPage()

    expect(await screen.findByRole('heading', { name: 'Findings' })).toBeInTheDocument()
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByRole('button', { name: 'Download' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Download' })).not.toBeInTheDocument()
  })

  it('renders plain text in a code block as before', async () => {
    served = artifact({ content_type: 'text/plain', title: 'log.txt', content: 'line one\nline two' })
    const { container } = renderPage()

    await screen.findByRole('button', { name: 'Download' })
    expect(container.querySelector('pre code')).toHaveTextContent('line one line two')
    expect(container.querySelector('img')).toBeNull()
    expect(screen.queryByRole('link', { name: 'Download' })).not.toBeInTheDocument()
  })
})
