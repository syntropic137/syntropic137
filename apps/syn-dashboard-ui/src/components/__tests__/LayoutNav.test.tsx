import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Layout } from '../Layout'

afterEach(() => vi.unstubAllGlobals())

describe('primary navigation', () => {
  it('has an Evals link to /evals that is active on an eval page', () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 503 })))
    render(
      <MemoryRouter initialEntries={['/evals/eval-1']}>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route path="evals/:evalId" element={<p>detail</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    const evals = screen.getAllByRole('link', { name: 'Evals' })
    expect(evals.length).toBeGreaterThan(0)
    for (const link of evals) {
      expect(link).toHaveAttribute('href', '/evals')
      expect(link).toHaveAttribute('aria-current', 'page')
    }
    for (const link of screen.getAllByRole('link', { name: 'Executions' })) {
      expect(link).not.toHaveAttribute('aria-current')
    }
  })
})
