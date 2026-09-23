import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SessionInventory } from '../SessionInventory'
import { getSessionInventory, getSessionInventoryPage, type InventoryPage, type InventoryStatus } from '../../../api/sessionInventory'

vi.mock('../../../api/sessionInventory', () => ({ getSessionInventory: vi.fn(), getSessionInventoryPage: vi.fn() }))
const snapshot: NonNullable<InventoryStatus['snapshot']> = {
  snapshot_id: 'snapshot-one', run: { execution_id: 'run', source_instance_id: 'source' },
  revision: 'revision-one', resolver_version: 'test', evidence_watermark: 2,
  coverage: { state: 'unknown' }, counts: { node: 2, edge: 0, membership: 0, capture: 0, gap: 0, binding: 0, retraction: 0 },
}
const status: InventoryStatus = { run: snapshot.run, snapshot, reconstruction_status: 'current', observed_evidence_watermark: 2, later_evidence_pending: false }
const page: InventoryPage = { snapshot, kind: 'node', items: [{ ref: { kind: 'transcript', source_instance_id: 'source', local_id: 'native-full-id', harness: 'fake' }, evidence: [] }], next_after: 0 }

beforeEach(() => { vi.mocked(getSessionInventory).mockResolvedValue(status); vi.mocked(getSessionInventoryPage).mockResolvedValue(page) })
afterEach(() => { cleanup(); vi.resetAllMocks() })

it('shows pending inventory without claiming an empty completed inventory', async () => {
  vi.mocked(getSessionInventory).mockResolvedValue({ ...status, snapshot: null, reconstruction_status: 'pending' })
  render(<SessionInventory executionId="run" />)
  expect(await screen.findByText('No published inventory yet.')).toBeTruthy()
  expect(getSessionInventoryPage).not.toHaveBeenCalled()
})

it('keeps pages pinned and replaces visible rows with the next bounded page', async () => {
  render(<SessionInventory executionId="run" />)
  expect(await screen.findByText('native-full-id')).toBeTruthy()
  vi.mocked(getSessionInventoryPage).mockResolvedValue({ ...page, items: [], next_after: null })
  fireEvent.click(screen.getByText('Next page'))
  expect(await screen.findByText('No sessions in this revision.')).toBeTruthy()
  expect(screen.queryByText('native-full-id')).toBeNull()
  expect(getSessionInventoryPage).toHaveBeenLastCalledWith('run', 'snapshot-one', 'node', 0, expect.any(AbortSignal))
})

it('clears the old inventory when a fresh access check fails', async () => {
  render(<SessionInventory executionId="run" />)
  await screen.findByText('native-full-id')
  vi.mocked(getSessionInventory).mockRejectedValue(new Error('Access denied'))
  fireEvent.click(screen.getByText('Load latest revision'))
  expect((await screen.findByRole('alert')).textContent).toContain('Access denied')
  expect(screen.queryByText('native-full-id')).toBeNull()
})

it('ignores a late response after leaving the run', async () => {
  let resolve!: (value: InventoryStatus) => void
  vi.mocked(getSessionInventory).mockReturnValue(new Promise(done => { resolve = done }))
  const view = render(<SessionInventory executionId="old-run" />)
  view.unmount()
  resolve(status)
  await waitFor(() => expect(getSessionInventoryPage).not.toHaveBeenCalled())
})

it('shows current expiry separately from the immutable receipt', async () => {
  render(<SessionInventory executionId="run" />)
  await screen.findByText('native-full-id')
  vi.mocked(getSessionInventoryPage).mockResolvedValue({
    snapshot, kind: 'capture', next_after: null,
    body_overrides: [{ archive_sha256: 'a'.repeat(64), status: 'expired' }],
    items: [{ node: { kind: 'transcript', source_instance_id: 'source', local_id: 'native', harness: 'codex' },
      destination: 'local', availability: 'present', receipt_sequence: 1, archived_byte_hash: 'a'.repeat(64),
      evidence: { producer_id: 'test', evidence_id: 'one', source_revision: '1', locator: 'test', extractor_version: '1' } }],
  })
  fireEvent.change(screen.getByLabelText('Inventory section'), { target: { value: 'capture' } })
  expect(await screen.findByText('Current local body: expired')).toBeTruthy()
  expect(screen.getByText('local availability recorded at capture: present')).toBeTruthy()
  expect(screen.queryByText('Open local transcript')).toBeNull()
})
