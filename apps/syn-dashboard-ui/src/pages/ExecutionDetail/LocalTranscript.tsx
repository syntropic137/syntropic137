import { useEffect, useState } from 'react'
import { getLocalTranscript } from '../../api/sessionInventory'

interface Props { executionId: string; harness: string; nativeId: string; revision: string }
interface Preview { text: string; url: string; size: number }

/** Opening always rechecks access; closing discards bytes and revokes the download URL. */
export function LocalTranscript({ executionId, harness, nativeId, revision }: Props) {
  const [open, setOpen] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    let url: string | undefined
    async function load() {
      try {
        const result = await getLocalTranscript(executionId, harness, nativeId, revision, controller.signal)
        if (controller.signal.aborted) return
        if (result.status !== 'present') throw new Error(`Transcript unavailable: ${result.status}`)
        if (result.archive_sha256 !== revision || typeof result.content_base64 !== 'string' || result.content_base64.length > 22369624) throw new Error('Invalid transcript revision')
        const raw = atob(result.content_base64)
        const bytes = Uint8Array.from(raw, c => c.charCodeAt(0))
        const digest = await crypto.subtle.digest('SHA-256', bytes)
        if (controller.signal.aborted) return
        const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('')
        if (hash !== revision || bytes.length !== result.size) throw new Error('Transcript integrity verification failed')
        let text: string
        try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes.slice(0, 32768), { stream: bytes.length > 32768 }) }
        catch { text = 'Binary transcript. Download the verified archive to inspect it.' }
        if (bytes.length > 32768) text += '\n[Preview limited to 32 KiB. Download contains the complete archive.]'
        url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }))
        setPreview({ text, url, size: bytes.length })
      } catch (reason) {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Unable to load transcript')
      }
    }
    void load()
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url) }
  }, [open, executionId, harness, nativeId, revision])
  function toggle() { setPreview(null); setError(null); setOpen(value => !value) }
  return <div className="mt-2 space-y-2">
    <button type="button" aria-expanded={open} onClick={toggle}>{open ? 'Close transcript' : 'Open local transcript'}</button>
    {open && <>
      {error && <p role="alert">{error}</p>}
      {!error && !preview && <p role="status">Loading transcript...</p>}
      {preview && <>
        <a href={preview.url} download={`transcript-${revision}.bin`}>Download exact archive ({preview.size} bytes)</a>
        <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all" aria-label="Transcript preview">{preview.text}</pre>
      </>}
    </>}
  </div>
}
