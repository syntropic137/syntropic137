import { transcriptPreview } from './transcriptPreview'
import { useEffect, useState } from 'react'
import { getLocalTranscript, type LocalTranscript as TranscriptResponse } from '../../api/sessionInventory'

interface Props { executionId: string; harness: string; nativeId: string; revision: string }
interface Preview { text: string; url: string; size: number }
interface PreviewUpdates {
  ready: (preview: Preview) => void
  failed: (message: string) => void
}

function decodeArchive(result: TranscriptResponse, revision: string): Uint8Array<ArrayBuffer> {
  if (result.status === 'expired') throw new Error('Transcript expired under retention. Session history remains available.')
  if (result.status === 'deleted') throw new Error('Transcript was deleted or retracted. Session history remains available.')
  if (result.status !== 'present') throw new Error(`Transcript unavailable: ${result.status}`)
  if (result.archive_sha256 !== revision || typeof result.content_base64 !== 'string' || result.content_base64.length > 22369624) {
    throw new Error('Invalid transcript revision')
  }
  return Uint8Array.from(atob(result.content_base64), c => c.charCodeAt(0))
}

async function verifiedArchive(props: Props, signal: AbortSignal): Promise<Uint8Array<ArrayBuffer>> {
  const result = await getLocalTranscript(props.executionId, props.harness, props.nativeId, props.revision, signal)
  signal.throwIfAborted()
  const bytes = decodeArchive(result, props.revision)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  signal.throwIfAborted()
  const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('')
  if (hash !== props.revision || bytes.length !== result.size) throw new Error('Transcript integrity verification failed')
  return bytes
}


function startPreview(props: Props, updates: PreviewUpdates): () => void {
  const controller = new AbortController()
  let url: string | undefined
  void verifiedArchive(props, controller.signal).then(bytes => {
    if (controller.signal.aborted) return
    url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }))
    updates.ready({ text: transcriptPreview(bytes), url, size: bytes.length })
  }).catch(reason => {
    if (controller.signal.aborted) return
    updates.failed(reason instanceof Error ? reason.message : 'Unable to load transcript')
  })
  return () => {
    controller.abort()
    if (url) URL.revokeObjectURL(url)
  }
}

function PreviewContent({ preview, error, revision }: { preview: Preview | null; error: string | null; revision: string }) {
  if (error) return <p role="alert">{error}</p>
  if (!preview) return <p role="status">Loading transcript...</p>
  return <>
    <a href={preview.url} download={`transcript-${revision}.bin`}>Download exact archive ({preview.size} bytes)</a>
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all" aria-label="Transcript preview">{preview.text}</pre>
  </>
}

/** Opening always rechecks access; closing discards bytes and revokes the download URL. */
export function LocalTranscript({ executionId, harness, nativeId, revision }: Props) {
  const [open, setOpen] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!open) return
    return startPreview({ executionId, harness, nativeId, revision }, { ready: setPreview, failed: setError })
  }, [open, executionId, harness, nativeId, revision])
  function toggle() { setPreview(null); setError(null); setOpen(value => !value) }
  return <div className="mt-2 space-y-2">
    <button type="button" aria-expanded={open} onClick={toggle}>{open ? 'Close transcript' : 'Open local transcript'}</button>
    {open && <PreviewContent preview={preview} error={error} revision={revision} />}
  </div>
}
