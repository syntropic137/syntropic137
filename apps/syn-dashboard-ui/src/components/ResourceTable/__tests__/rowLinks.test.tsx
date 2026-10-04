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

// Codex review on #1566: events from a row's own controls bubble to the row, so
// pressing Space on its checkbox or Enter on its action button also opened the
// detail page. Each list below carries both kinds of control.
const SELECTION = {
  selectedIds: new Set<string>(),
  onToggleRow: () => {},
  onSelectAll: () => {},
  onClearSelection: () => {},
}

function TableWithControls() {
  return (
    <ResourceTable<Row>
      rows={ROWS}
      loading={false}
      emptyState={null}
      getRowId={(r) => r.id}
      columns={[{ key: 'id', label: 'ID', render: (r) => r.id }]}
      rowHref={(r) => `/executions/${r.id}`}
      rowActions={() => <button type="button">Copy id</button>}
      selection={SELECTION}
    />
  )
}

function CardsWithControls() {
  return (
    <ResourceCardList<Row>
      rows={ROWS}
      loading={false}
      emptyState={null}
      getRowId={(r) => r.id}
      renderCard={(r) => (
        <>
          {r.id}
          <button type="button">Copy id</button>
        </>
      )}
      rowHref={(r) => `/executions/${r.id}`}
      selection={SELECTION}
    />
  )
}

describe.each([
  ['ResourceTable', TableWithControls],
  ['ResourceCardList', CardsWithControls],
])('%s nested controls do not follow the row link', (_name, List) => {
  const controls: [string, () => HTMLElement][] = [
    ['checkbox', () => screen.getByRole('checkbox', { name: 'Select exec-42' })],
    ['button', () => screen.getByRole('button', { name: 'Copy id' })],
  ]

  describe.each(controls)('on the nested %s', (_kind, control) => {
    it.each([['Enter'], [' ']])('key %j does not navigate', (key) => {
      renderAt(<List />)
      fireEvent.keyDown(control(), { key })
      expect(screen.queryByText('detail page')).toBeNull()
      expect(open).not.toHaveBeenCalled()
    })

    it.each([[{}], [{ metaKey: true }], [{ ctrlKey: true }]])(
      'click %j neither navigates nor opens a tab',
      (mods) => {
        renderAt(<List />)
        fireEvent.click(control(), mods)
        expect(screen.queryByText('detail page')).toBeNull()
        expect(open).not.toHaveBeenCalled()
      },
    )

    it('middle-click opens no tab', () => {
      renderAt(<List />)
      fireEvent(control(), new MouseEvent('auxclick', { bubbles: true, button: 1 }))
      expect(open).not.toHaveBeenCalled()
    })
  })

  it('Enter on the row itself still navigates', () => {
    renderAt(<List />)
    fireEvent.keyDown(screen.getByRole('link'), { key: 'Enter' })
    expect(screen.getByText('detail page')).toBeTruthy()
  })
})
