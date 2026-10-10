/**
 * Per-viewer conveniences in localStorage (Outcomes range, seen runs). Every
 * read and write is guarded: private windows, blocked storage and previews
 * throw or return nothing, and the Overview must render the same without it.
 */
export function readViewer(key: string): string | null {
  try {
    return globalThis.localStorage?.getItem(key) ?? null
  } catch {
    return null
  }
}

export function writeViewer(key: string, value: string | null): void {
  try {
    if (value === null) globalThis.localStorage?.removeItem(key)
    else globalThis.localStorage?.setItem(key, value)
  } catch {
    // Storage unavailable: the choice lasts for this page view only.
  }
}
