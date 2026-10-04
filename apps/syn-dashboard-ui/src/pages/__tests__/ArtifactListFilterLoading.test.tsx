/**
 * Switching the artifact type must show that the list is updating.
 *
 * The owner's report: "when switching types, there is no loading indicator and
 * it looks like it's not working". The previous rows stayed on screen exactly
 * as though they were the answer, because the hook's `loading` settled on
 * mount and never said otherwise again.
 *
 * Served over `fetch`, with the narrowed answer held back by hand, so the
 * whole path runs: the select, `useArtifactList`'s fetcher, `useLatestPage`'s
 * bookkeeping, and the page that renders it.
 */

import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { __resetActivityStreamForTests } from '../../hooks/useActivityStream'
import type { ArtifactSummary } from '../../types'
import { ArtifactList } from '../ArtifactList'

function artifact(id: string, artifact_type: string, title: string): ArtifactSummary {
  return {
    id,
    workflow_id: null,
    phase_id: null,
    artifact_type,
    title,
    size_bytes: 10,
    created_at: '2026-10-01T00:00:00Z',
  }
}

const EVERY_TYPE = [artifact('a1', 'text', 'Release notes'), artifact('a2', 'code', 'patch.py')]
const CODE_ONLY = [artifact('a2', 'code', 'patch.py')]

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function listing(artifacts: ArtifactSummary[]): Response {
  return json({
    artifacts,
    total: artifacts.length,
    type_counts: { text: 1, code: 1 },
    excluded_undated: 0,
  })
}

let releaseCodeOnly: () => void = () => {}

class SilentEventSource {
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((e: MessageEvent<string>) => void) | null = null
  close(): void {}
}

beforeEach(() => {
  const codeOnly = new Promise<void>((resolve) => {
    releaseCodeOnly = resolve
  })
  vi.stubGlobal('EventSource', SilentEventSource)
  vi.stubGlobal('fetch', async (input: RequestInfo | URL): Promise<Response> => {
    const url = new URL(
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
      'http://dashboard',
    )
    if (url.pathname !== '/api/v1/artifacts') throw new Error(`No fake endpoint for ${url}`)
    if (url.searchParams.get('artifact_type') === 'code') {
      await codeOnly
      return listing(CODE_ONLY)
    }
    return listing(EVERY_TYPE)
  })
})

afterEach(() => {
  __resetActivityStreamForTests()
  vi.unstubAllGlobals()
})

describe('Artifacts type filter', () => {
  it('dims the previous rows under an "Updating" status until the new type lands', async () => {
    render(
      <MemoryRouter>
        <ArtifactList />
      </MemoryRouter>,
    )
    await screen.findByText('Release notes')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Artifact type'), { target: { value: 'code' } })

    // Previous rows kept rather than blanked, and marked as not the answer.
    expect(await screen.findByRole('status')).toHaveTextContent('Updating')
    const previous = screen.getByText('Release notes')
    expect(previous.closest('[aria-busy="true"]')).not.toBeNull()

    await act(async () => releaseCodeOnly())

    expect(await screen.findByText('patch.py')).toBeInTheDocument()
    expect(screen.queryByText('Release notes')).not.toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
