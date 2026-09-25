import { webcrypto, createHash } from 'node:crypto'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { LocalTranscript } from '../LocalTranscript'
import { getLocalTranscript } from '../../../api/sessionInventory'

vi.mock('../../../api/sessionInventory', () => ({ getLocalTranscript: vi.fn() }))
const bytes = Buffer.from('<script>not executable</script>\r\n')
const revision = createHash('sha256').update(bytes).digest('hex')
const props = { executionId: 'run', harness: 'codex', nativeId: 'native', revision }
beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto)
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() }))
  vi.mocked(getLocalTranscript).mockResolvedValue({ status: 'present', archive_sha256: revision, size: bytes.length, content_format: 'native', content_base64: bytes.toString('base64') })
})
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals() })

it('loads only on request and releases the download when closed', async () => {
  render(<LocalTranscript {...props} />)
  expect(getLocalTranscript).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('Open local transcript'))
  expect((await screen.findByLabelText('Transcript preview')).textContent).toContain('<script>not executable</script>')
  expect(document.querySelector('script')).toBeNull()
  expect(screen.getByRole('link').getAttribute('href')).toBe('blob:test')
  fireEvent.click(screen.getByText('Close transcript'))
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test')
  expect(screen.queryByLabelText('Transcript preview')).toBeNull()
})

it('rechecks access after reopening and clears prior content on denial', async () => {
  render(<LocalTranscript {...props} />)
  fireEvent.click(screen.getByText('Open local transcript'))
  await screen.findByLabelText('Transcript preview')
  fireEvent.click(screen.getByText('Close transcript'))
  vi.mocked(getLocalTranscript).mockRejectedValue(new Error('Transcript access denied'))
  fireEvent.click(screen.getByText('Open local transcript'))
  expect((await screen.findByRole('alert')).textContent).toContain('Transcript access denied')
  expect(screen.queryByRole('link')).toBeNull()
  expect(getLocalTranscript).toHaveBeenCalledTimes(2)
})

it('rejects corrupted content before creating a download', async () => {
  vi.mocked(getLocalTranscript).mockResolvedValue({ status: 'present', archive_sha256: revision, size: 1, content_format: 'native', content_base64: 'YQ==' })
  render(<LocalTranscript {...props} />)
  fireEvent.click(screen.getByText('Open local transcript'))
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('integrity verification failed'))
  expect(URL.createObjectURL).not.toHaveBeenCalled()
})

it('does not expose a response arriving after the preview was closed', async () => {
  let resolve!: (value: Awaited<ReturnType<typeof getLocalTranscript>>) => void
  vi.mocked(getLocalTranscript).mockReturnValue(new Promise(done => { resolve = done }))
  render(<LocalTranscript {...props} />)
  fireEvent.click(screen.getByText('Open local transcript'))
  const signal = vi.mocked(getLocalTranscript).mock.calls[0]![4]!
  fireEvent.click(screen.getByText('Close transcript'))
  expect(signal.aborted).toBe(true)
  resolve({ status: 'present', archive_sha256: revision, size: bytes.length, content_format: 'native', content_base64: bytes.toString('base64') })
  await waitFor(() => expect(screen.queryByRole('link')).toBeNull())
  expect(URL.createObjectURL).not.toHaveBeenCalled()
})

it('explains expired bodies without offering a download', async () => {
  vi.mocked(getLocalTranscript).mockResolvedValue({ status: 'expired', archive_sha256: revision, size: bytes.length, content_format: 'native', content_base64: null })
  render(<LocalTranscript {...props} />)
  fireEvent.click(screen.getByText('Open local transcript'))
  expect((await screen.findByRole('alert')).textContent).toContain('Session history remains available')
  expect(screen.queryByRole('link')).toBeNull()
  expect(URL.createObjectURL).not.toHaveBeenCalled()
})

it('explains deleted bodies separately from retention expiry', async () => {
  vi.mocked(getLocalTranscript).mockResolvedValue({ status: 'deleted', archive_sha256: revision, size: bytes.length, content_format: 'native', content_base64: null })
  render(<LocalTranscript {...props} />)
  fireEvent.click(screen.getByText('Open local transcript'))
  const alert = (await screen.findByRole('alert')).textContent
  expect(alert).toContain('deleted or retracted')
  expect(alert).toContain('Session history remains available')
  expect(screen.queryByRole('link')).toBeNull()
})
