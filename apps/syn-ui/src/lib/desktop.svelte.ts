/**
 * Tauri shell wiring (apps/syn-desktop/README.md, "Wiring the web app").
 * main.ts imports this lazily and only inside the desktop app, so the web
 * build's first-load JS does not grow.
 */
import { API_BASE, configureClient } from '@syn137/syn-ui-data'
import { setLiveState, startDesktop } from '../../../syn-desktop/bridge/index.ts'
import { live } from './live.svelte'
import { router } from './router'

function openCommandPalette(): void {
  // Same event App.svelte dispatches for Cmd/Ctrl+K inside the page.
  window.dispatchEvent(new CustomEvent('sky:command'))
}

/** Wire shell events, apply the saved API root, and mirror Live into the tray dot. */
export async function connectDesktop(): Promise<() => void> {
  const stop = await startDesktop({
    navigate: (path) => router.navigate(path),
    openCommandPalette,
    // openSettings is left unset until syn-ui has a Settings route.
    configureApi: (baseUrl) => configureClient({ baseUrl: baseUrl ?? API_BASE }),
  })
  const stopTray = $effect.root(() => {
    $effect(() => {
      void setLiveState(live.state)
    })
  })
  return () => {
    stop()
    stopTray()
  }
}
