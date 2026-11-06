/**
 * Recovery for a page whose chunk will not load after a deploy (#2188).
 *
 * Every build renames its hashed chunks and the gateway keeps only the new
 * ones, so a tab opened before a deploy asks for files that now 404. index.html
 * is served no-cache, so one reload lands on the new build. That reload is tried
 * once per tab: the attempt is recorded in sessionStorage, which survives the
 * reload, and cleared by the next page that loads. A second failure is a real
 * one, and the caller shows it.
 *
 * Only route navigation recovers this way, not every lazy chunk (no
 * `vite:preloadError` listener): hover prefetch and the feedback capture also
 * import chunks, and reloading under someone mid-task would lose their work.
 */

const ATTEMPT_KEY = 'syn-ui:chunk-reload'

/** The browser, as far as this needs it. Tests pass a double. */
export interface ReloadHost {
  readonly storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
  isOnline(): boolean
  reload(): void
}

export class ChunkReload {
  private reloading = false

  constructor(private readonly host: ReloadHost) {}

  /**
   * A page's chunk failed to load. True: the page is reloading into the
   * current build, so show nothing. False: show the error, because a reload was
   * already tried, the browser is offline (a reload would only reach the
   * browser's own offline page), or sessionStorage is unavailable and nothing
   * would stop a reload loop.
   */
  recover(): boolean {
    if (this.reloading) return true
    if (!this.host.isOnline()) return false
    try {
      if (this.host.storage.getItem(ATTEMPT_KEY) !== null) return false
      this.host.storage.setItem(ATTEMPT_KEY, String(Date.now()))
    } catch {
      return false
    }
    this.reloading = true
    this.host.reload()
    return true
  }

  /** A page's chunk loaded, so the next deploy may reload this tab again. */
  loaded(): void {
    try {
      this.host.storage.removeItem(ATTEMPT_KEY)
    } catch {
      // Unavailable storage never recorded an attempt, so there is nothing to clear.
    }
  }
}

export const chunkReload = new ChunkReload({
  get storage() {
    return sessionStorage
  },
  isOnline: () => navigator.onLine,
  reload: () => location.reload(),
})
