/**
 * Which shell overlay is open: the Command palette (⌘K, the search
 * buttons, the desktop shortcut) or the `?` shortcuts overlay. Each one's
 * chunk loads on first open (`mounted`), never in the first load.
 */
class Overlays {
  palette = $state(false)
  shortcuts = $state(false)
  paletteMounted = $state(false)
  shortcutsMounted = $state(false)

  openPalette(): void {
    this.shortcuts = false
    this.paletteMounted = true
    this.palette = true
  }

  openShortcuts(): void {
    this.palette = false
    this.shortcutsMounted = true
    this.shortcuts = true
  }
}

export const overlays = new Overlays()

/** The one event every entry point fires (App's ⌘K, the search buttons, the desktop bridge). */
export const COMMAND_EVENT = 'sky:command'

export function requestPalette(): void {
  window.dispatchEvent(new CustomEvent(COMMAND_EVENT))
}

/** Apple keyboards show ⌘, everyone else Ctrl. */
export const APPLE = typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent)
