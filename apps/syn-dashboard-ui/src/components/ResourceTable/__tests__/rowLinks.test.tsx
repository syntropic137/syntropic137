/**
 * List rows open in a new tab on cmd/ctrl-click and middle-click, and navigate
 * in-app on a plain click or Enter.
 *
 * Driven through ResourceTable and ResourceCardList inside a real router, so a
 * plain click is observed as the route actually changing, not as a callback.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ResourceCardList, ResourceTable } from '..'

interface Row {
  id: string
}

const ROWS: Row[] = [{ id: 'exec-42' }]

function Table() {
  return (
    <ResourceTable<Row>
      rows={ROWS}
      loading={false}
      emptyState={null}
      getRowId={(r) => r.id}
      columns={[{ key: 'id', label: 'ID', render: (r) => r.id }]}
      rowHref={(r) => `/executions/${r.id}`}
    />
  )
}

function Cards() {
  return (
    <ResourceCardList<Row>
      rows={ROWS}
      loading={false}
      emptyState={null}
      getRowId={(r) => r.id}
      renderCard={(r) => r.id}
      rowHref={(r) => `/executions/${r.id}`}
    />
  )
}

function renderAt(list: React.ReactElement) {
  return render(
    <MemoryRouter initialEntries={['/executions']}>
      <Routes>
        <Route path="/executions" element={list} />
        <Route path="/executions/:id" element={<p>detail page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

let open: ReturnType<typeof vi.fn>

beforeEach(() => {
  open = vi.fn()
  vi.stubGlobal('open', open)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe.each([
  ['ResourceTable', Table],
  ['ResourceCardList', Cards],
])('%s row links', (_name, List) => {
  const row = () => screen.getByRole('link')

  it('plain click navigates in-app and opens no tab', () => {
    renderAt(<List />)
    fireEvent.click(row())
    expect(screen.getByText('detail page')).toBeTruthy()
    expect(open).not.toHaveBeenCalled()
  })

  it.each([['metaKey'], ['ctrlKey']])('%s-click opens a new tab and stays put', (key) => {
    renderAt(<List />)
    fireEvent.click(row(), { [key]: true })
    expect(open).toHaveBeenCalledWith('/executions/exec-42', '_blank', 'noopener')
    expect(screen.queryByText('detail page')).toBeNull()
  })

  it('middle-click opens a new tab', () => {
    renderAt(<List />)
    fireEvent(row(), new MouseEvent('auxclick', { bubbles: true, button: 1 }))
    expect(open).toHaveBeenCalledWith('/executions/exec-42', '_blank', 'noopener')
    expect(screen.queryByText('detail page')).toBeNull()
  })

  it('is focusable and Enter navigates', () => {
    renderAt(<List />)
    expect(row().tabIndex).toBe(0)
    fireEvent.keyDown(row(), { key: 'Enter' })
    expect(screen.getByText('detail page')).toBeTruthy()
  })
})
