/**
 * Tiny copy-to-clipboard helper with transient "just copied" state.
 *
 * Returns the kind that was last copied (so different buttons can show their
 * own "Copied!" indicator) and a `copy(kind, text)` async function. State
 * auto-clears after `resetMs` (default 1500).
 */

import { useEffect, useState } from 'react'

export type CopyKind = 'ids' | 'claude'

export interface UseCopyFeedback {
  lastCopied: CopyKind | null
  copy: (kind: CopyKind, text: string) => Promise<void>
}

export function useCopyFeedback(resetMs = 1500): UseCopyFeedback {
  const [lastCopied, setLastCopied] = useState<CopyKind | null>(null)

  useEffect(() => {
    if (lastCopied === null) return
    const id = setTimeout(() => setLastCopied(null), resetMs)
    return () => clearTimeout(id)
  }, [lastCopied, resetMs])

  const copy = async (kind: CopyKind, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setLastCopied(kind)
    } catch {
      // ignore — clipboard API can fail in older browsers
    }
  }

  return { lastCopied, copy }
}
