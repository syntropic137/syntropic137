import '@syn137/skyline-themes/all.css'
import '@syn137/skyline-svelte-v5/styles.css'
import './app.css'

import { mount } from 'svelte'
import { configureClient } from '@syn137/syn-ui-data'
import App from './App.svelte'

configureClient({ fixtures: import.meta.env.VITE_SYN_FIXTURES === '1' })

// Desktop app (apps/syn-desktop): Tauri exposes window.__TAURI__ (withGlobalTauri).
// The bridge is a lazy chunk, so the plain browser build pays only this check.
// Awaited so a saved API root is applied before the first request.
if ('__TAURI__' in window) {
  try {
    const { connectDesktop } = await import('./lib/desktop.svelte')
    await connectDesktop()
  } catch (err) {
    console.warn('[syn-ui] desktop bridge failed to start', err)
  }
}

const target = document.getElementById('app')
if (!target) throw new Error('#app missing from index.html')

export default mount(App, { target })
