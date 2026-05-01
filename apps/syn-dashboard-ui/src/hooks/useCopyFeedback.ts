/**
 * Tiny copy-to-clipboard helper with transient "just copied" state.
 *
 * Generic over a `Kind` string union so different buttons can show their own
 * "Copied!" indicator (e.g. `'ids' | 'agent'`). State auto-clears after
 * `resetMs` (default 1500).
 */

import { useEffect, useState } from 'react'

export interface UseCopyFeedback<Kind extends string> {
  lastCopied: Kind | null
  copy: (kind: Kind, text: string) => Promise<void>
}

export function useCopyFeedback<Kind extends string>(resetMs = 1500): UseCopyFeedback<Kind> {
  const [lastCopied, setLastCopied] = useState<Kind | null>(null)

  useEffect(() => {
    if (lastCopied === null) return
    const id = setTimeout(() => setLastCopied(null), resetMs)
    return () => clearTimeout(id)
  }, [lastCopied, resetMs])

  const copy = async (kind: Kind, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setLastCopied(kind)
    } catch {
      // ignore — clipboard API can fail in older browsers
    }
  }

  return { lastCopied, copy }
}
