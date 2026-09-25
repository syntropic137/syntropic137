import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SessionInventory } from '../SessionInventory'
import { ApiError } from '../../../api/base'
import {
  getSessionInventory, getSessionInventoryNode, getSessionInventoryPage,
  type InventoryKind, type InventoryPage, type InventoryStatus,
} from '../../../api/sessionInventory'

vi.mock('../../../api/sessionInventory', () => ({
  getSessionInventory: vi.fn(), getSessionInventoryPage: vi.fn(), getSessionInventoryNode: vi.fn(), getLocalTranscript: vi.fn(),
}))

type Snapshot = NonNullable<InventoryStatus['snapshot']>
const run = { execution_id: 'run', source_instance_id: 'source' }
const snapshot: Snapshot = {
  snapshot_id: 'snapshot-one', run, revision: 'revision-one', resolver_version: 'test', evidence_watermark: 2,
  coverage: { state: 'open' }, counts: { node: 3, edge: 1, membership: 2, capture: 1, gap: 0, binding: 0, retraction: 0 },
}
const summary: InventoryStatus['summary'] = {
  complete: false, coverage_state: 'open', coverage_display: 'open: more sessions may still appear', revision: 'revision-one',
  distinct_sessions: 3, platform_sessions: 1, invocations: 0, native_transcripts: 2, gaps: 0, namespaces: [],
  counts_display: '1 platform session, 2 native transcripts (claude 2), 0 invocations, 0 gaps',
  remote_replication: 'enabled', follow_up_command: 'syn execution sessions run --all',
}
const status: InventoryStatus = { run, snapshot, reconstruction_status: 'current', observed_evidence_watermark: 2, later_evidence_pending: false, summary }
const evidence = { producer_id: 'p', evidence_id: 'e', source_revision: '1', locator: 'l', extractor_version: '1' }
const platform = { kind: 'platform' as const, source_instance_id: 'source', local_id: 'platform-session-full-id' }
const native = { kind: 'transcript' as const, source_instance_id: 'source', local_id: 'native-full-id', harness: 'claude' }
const child = { kind: 'transcript' as const, source_instance_id: 'source', local_id: 'native-child-id', harness: 'claude' }
const key = (c: string) => c.repeat(64)

function page(kind: InventoryKind, items: InventoryPage['items'], item_keys: InventoryPage['item_keys'], next: string | null = null, extra: Partial<InventoryPage> = {}): InventoryPage {
  return { snapshot, kind, filters: {}, items, item_keys, next_cursor: next, ...extra }
}

const pages: Partial<Record<InventoryKind, InventoryPage[]>> = {}
function serve(kind: InventoryKind, ...list: InventoryPage[]) { pages[kind] = list }

beforeEach(() => {
  for (const kind of Object.keys(pages)) delete pages[kind as InventoryKind]
  serve('node',
    page('node', [{ ref: platform, evidence: [] }], [{ node_key: key('p') }], 'node-cursor'),
    page('node', [{ ref: native, evidence: [] }, { ref: child, evidence: [] }], [{ node_key: key('n') }, { node_key: key('c') }]))
  serve('membership', page('membership', [
    { node: platform, run, phase_id: 'phase-plan', attempt_id: 'attempt-1', confidence: 'registered', evidence: [] },
    { node: native, run, phase_id: 'phase-plan', attempt_id: 'attempt-1', confidence: 'registered', evidence: [] },
  ], [{ node_key: key('p') }, { node_key: key('n') }]))
  serve('edge', page('edge', [{ parent: native, child, relation: 'spawn', confidence: 'corroborated', evidence: [] }], [{ node_key: key('n'), peer_key: key('c') }]))
  serve('capture', page('capture', [{ node: native, destination: 'local', availability: 'present', receipt_sequence: 1, archived_byte_hash: 'a'.repeat(64), evidence }],
    [{ node_key: key('n') }], null, { body_overrides: [{ archive_sha256: 'a'.repeat(64), status: 'expired' }] }))
  vi.mocked(getSessionInventory).mockResolvedValue(status)
  vi.mocked(getSessionInventoryPage).mockImplementation(async (_e, _s, kind, cursor) => {
    const list = pages[kind] ?? [page(kind, [], [])]
    return cursor === null ? list[0]! : list[1]!
  })
})
afterEach(() => { cleanup(); vi.resetAllMocks() })

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.search}</output>
}

function renderAt(url = '/executions/run') {
  return render(<MemoryRouter initialEntries={[url]}>
    <Routes>
      <Route path="/executions/:id" element={<><SessionInventory executionId="run" /><LocationProbe /></>} />
      <Route path="/sessions/:id" element={<p>platform session page</p>} />
    </Routes>
  </MemoryRouter>)
}

it('traverses every page of every section of the pinned revision', async () => {
  renderAt()
  expect(await screen.findByText('native-child-id')).toBeTruthy()
  const calls = vi.mocked(getSessionInventoryPage).mock.calls
  expect(calls.map(c => c[2])).toEqual(['node', 'node', 'membership', 'edge', 'capture', 'gap', 'binding', 'retraction'])
  expect(calls[1]![3]).toBe('node-cursor')
  expect(calls.every(c => c[1] === 'snapshot-one')).toBe(true)
})

it('shows server counts with platform and native separated, grouped by phase attempt, and unlinked sessions', async () => {
  renderAt()
  expect(await screen.findByText(summary.counts_display)).toBeTruthy()
  expect(screen.getByText('Platform sessions').nextSibling?.textContent).toBe('1')
  expect(screen.getByText('Native transcripts').nextSibling?.textContent).toBe('2')
  const group = screen.getByRole('region', { name: 'Phase phase-plan attempt attempt-1' })
  expect(within(group).getByText('platform-session-full-id')).toBeTruthy()
  const unlinked = screen.getByRole('region', { name: 'Unlinked sessions' })
  expect(within(unlinked).getByText('native-child-id')).toBeTruthy()
  expect(screen.getByText('recorded present; now expired')).toBeTruthy()
})

it('links only platform ids to the platform session page', async () => {
  renderAt()
  await screen.findByText('native-full-id')
  expect(screen.getByText('platform-session-full-id').closest('a')?.getAttribute('href')).toBe('/sessions/platform-session-full-id')
  expect(screen.getByText('native-full-id').closest('a')).toBeNull()
  expect(document.querySelectorAll('a[href*="native"]').length).toBe(0)
})

it('shows partial coverage and remote-disabled as distinct notices', async () => {
  vi.mocked(getSessionInventory).mockResolvedValue({ ...status, summary: { ...summary, remote_replication: 'disabled' } })
  renderAt()
  await screen.findByText('native-full-id')
  expect(document.querySelector('[data-state="partial"]')?.textContent).toContain('open: more sessions')
  expect(document.querySelector('[data-state="remote-disabled"]')).toBeTruthy()
  expect(screen.getAllByText('disabled').length).toBeGreaterThan(0)
})

it('shows unsupported distinctly from partial', async () => {
  vi.mocked(getSessionInventory).mockResolvedValue({ ...status, summary: { ...summary, coverage_state: 'unsupported' } })
  renderAt()
  await screen.findByText('native-full-id')
  expect(document.querySelector('[data-state="unsupported"]')).toBeTruthy()
  expect(document.querySelector('[data-state="partial"]')).toBeNull()
})

it('shows complete only when the server says so', async () => {
  vi.mocked(getSessionInventory).mockResolvedValue({ ...status, summary: { ...summary, complete: true, coverage_state: 'reconciled' } })
  renderAt()
  await screen.findByText('native-full-id')
  expect(document.querySelector('[data-state="complete"]')).toBeTruthy()
})

it('distinguishes loading, not published and empty', async () => {
  let resolve!: (value: InventoryStatus) => void
  vi.mocked(getSessionInventory).mockReturnValue(new Promise(done => { resolve = done }))
  renderAt()
  expect(screen.getByText('Loading session inventory...')).toBeTruthy()
  resolve({ ...status, snapshot: null, reconstruction_status: 'pending' })
  expect(await screen.findByText(/No published inventory yet/)).toBeTruthy()
  expect(getSessionInventoryPage).not.toHaveBeenCalled()
  cleanup()
  vi.mocked(getSessionInventory).mockResolvedValue(status)
  serve('node', page('node', [], []))
  renderAt()
  expect(await screen.findByText('No sessions in this revision.')).toBeTruthy()
})

it('distinguishes permission denied from an expired revision', async () => {
  vi.mocked(getSessionInventory).mockRejectedValue(new ApiError(403, 'Forbidden'))
  renderAt()
  expect((await screen.findByRole('alert')).dataset.state).toBe('permission-denied')
  cleanup()
  vi.mocked(getSessionInventory).mockResolvedValue(status)
  vi.mocked(getSessionInventoryPage).mockRejectedValue(new ApiError(410, { code: 'cursor_expired', message: 'Pinned inventory revision is no longer available', restart: true }))
  renderAt()
  const alert = await screen.findByRole('alert')
  expect(alert.dataset.state).toBe('expired')
  expect(alert.textContent).toContain('no longer available')
})

it('clears the old inventory when a fresh access check fails', async () => {
  renderAt()
  await screen.findByText('native-full-id')
  vi.mocked(getSessionInventory).mockRejectedValue(new ApiError(401, 'Access denied'))
  fireEvent.click(screen.getByText('Load latest revision'))
  expect((await screen.findByRole('alert')).textContent).toContain('Access denied')
  expect(screen.queryByText('native-full-id')).toBeNull()
})

it('reads phase and attempt filters from the URL and writes them back', async () => {
  renderAt('/executions/run?inventory_phase=phase-plan&inventory_attempt=attempt-1')
  await screen.findByText('native-full-id')
  expect(vi.mocked(getSessionInventoryPage).mock.calls.every(c => c[5]?.phase_id === 'phase-plan' && c[5]?.attempt_id === 'attempt-1')).toBe(true)
  fireEvent.click(screen.getByText('Clear filter'))
  await waitFor(() => expect(screen.getByTestId('location').textContent).toBe(''))
  fireEvent.change(screen.getByLabelText('Phase filter'), { target: { value: 'phase-build' } })
  fireEvent.click(screen.getByText('Apply filter'))
  await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('?inventory_phase=phase-build'))
  await waitFor(() => expect(vi.mocked(getSessionInventoryPage).mock.calls.at(-1)![5]?.phase_id).toBe('phase-build'))
})

it('resolves a lineage endpoint outside the loaded set through the node lookup', async () => {
  serve('node', page('node', [{ ref: native, evidence: [] }], [{ node_key: key('n') }]))
  vi.mocked(getSessionInventoryNode).mockResolvedValue({ snapshot_id: 'snapshot-one', node_key: key('c'), status: 'resolved', node: { ref: child, evidence: [] } })
  renderAt()
  fireEvent.click(await screen.findByText('Show lineage (1)'))
  expect(await screen.findByText(/in this revision, outside the current filter/)).toBeTruthy()
  expect(getSessionInventoryNode).toHaveBeenCalledWith('run', 'snapshot-one', key('c'))
})

it('moves focus between rows with arrow keys and toggles lineage with Enter', async () => {
  renderAt()
  await screen.findByText('native-full-id')
  const rows = Array.from(document.querySelectorAll<HTMLElement>('[data-inventory-row]'))
  expect(rows.length).toBe(3)
  expect(rows.filter(row => row.tabIndex === 0).length).toBe(1)
  rows[0]!.focus()
  fireEvent.keyDown(rows[0]!, { key: 'ArrowDown' })
  expect(document.activeElement).toBe(rows[1])
  fireEvent.keyDown(rows[1]!, { key: 'End' })
  expect(document.activeElement).toBe(rows[2])
  fireEvent.keyDown(rows[2]!, { key: 'Home' })
  expect(document.activeElement).toBe(rows[0])
  const withLineage = rows.find(row => row.getAttribute('aria-expanded') !== null)!
  fireEvent.keyDown(withLineage, { key: 'Enter' })
  expect(withLineage.getAttribute('aria-expanded')).toBe('true')
})

it('copies the run identity and full session ids', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  renderAt()
  await screen.findByText('native-full-id')
  fireEvent.click(screen.getByText('Copy run identity'))
  await waitFor(() => expect(writeText).toHaveBeenCalled())
  expect(JSON.parse(writeText.mock.calls[0]![0] as string)).toEqual({ source_instance_id: 'source', execution_id: 'run', revision: 'revision-one', snapshot_id: 'snapshot-one' })
  fireEvent.click(screen.getByLabelText('Copy transcript:claude ID native-full-id'))
  await waitFor(() => expect(writeText).toHaveBeenLastCalledWith('native-full-id'))
})

it('ignores a late response after leaving the run', async () => {
  let resolve!: (value: InventoryStatus) => void
  vi.mocked(getSessionInventory).mockReturnValue(new Promise(done => { resolve = done }))
  const view = renderAt()
  view.unmount()
  resolve(status)
  await waitFor(() => expect(getSessionInventoryPage).not.toHaveBeenCalled())
})
