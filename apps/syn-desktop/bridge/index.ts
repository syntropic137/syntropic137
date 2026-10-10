/**
 * Desktop bridge: what apps/syn-ui imports to talk to the Tauri shell.
 *
 * Every export is safe in a plain browser: when the page is not running inside
 * apps/syn-desktop, listeners return a no-op unsubscribe and commands resolve
 * to null. The module has no dependencies (it uses the `window.__TAURI__`
 * global that `app.withGlobalTauri` exposes), so importing it adds a few
 * hundred bytes to the web build and no Tauri packages.
 *
 * Typical wiring in the app's startup (apps/syn-ui/src/main.ts):
 *
 *   import { startDesktop } from 'syn-desktop/bridge'
 *   import { configureClient, API_BASE } from '@syn137/syn-ui-data'
 *
 *   void startDesktop({
 *     navigate: (path) => router.go(path),
 *     openCommandPalette: () => palette.open(),
 *     openSettings: () => router.go('/settings'),
 *     configureApi: (baseUrl) => configureClient({ baseUrl: baseUrl ?? API_BASE }),
 *   })
 *
 * and, wherever the live state changes: `void setLiveState(live.state)`.
 *
 * Event and command names must match apps/syn-desktop/src-tauri/src/lib.rs.
 */

/** Mirrors `LiveState` in @syn137/skyline-core/patterns (kept local: zero deps). */
export type LiveState = 'live' | 'connecting' | 'offline' | 'fixtures'

export interface DesktopSettings {
  /** Absolute API root such as "http://localhost:8137/api/v1", or null for the default. */
  apiBaseUrl: string | null
  /** Global Command palette accelerator, "" when disabled. Default "CmdOrCtrl+K". */
  globalShortcut: string
}

export type Unsubscribe = () => void

export const EVENTS = {
  commandPalette: 'syn://command-palette',
  navigate: 'syn://navigate',
  openSettings: 'syn://open-settings',
  settingsChanged: 'syn://settings-changed',
} as const

/**
 * API root the desktop app uses when none is saved and there is no dev proxy:
 * the selfhost gateway, same as the CLI (apps/syn-cli-node/src/constants.ts,
 * SELFHOST_GATEWAY_PORT + API_PREFIX). The dev API without the gateway is
 * "http://127.0.0.1:9137" (no prefix).
 */
export const DEFAULT_DESKTOP_API_BASE_URL = 'http://localhost:8137/api/v1'

/** Port of the apps/syn-ui vite dev server (tauri.conf.json build.devUrl). */
const DEV_SERVER_PORT = '5174'

// ------------------------------------------------------------------ runtime

interface TauriEvent<T> {
  payload: T
}

interface TauriGlobal {
  core: { invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> }
  event: {
    listen<T>(event: string, handler: (event: TauriEvent<T>) => void): Promise<() => void>
  }
}

function tauri(): TauriGlobal | null {
  const g = globalThis as { __TAURI__?: TauriGlobal }
  return g.__TAURI__?.core && g.__TAURI__.event ? g.__TAURI__ : null
}

/** True when the page runs inside the Syntropic137 desktop app. */
export function isDesktop(): boolean {
  return tauri() !== null
}

const noop: Unsubscribe = () => {}

/**
 * Subscribe to a shell event. Returns a synchronous unsubscribe, so it can be
 * returned straight from a Svelte `$effect` even though Tauri's listen is async.
 */
function on<T>(name: string, cb: (payload: T) => void): Unsubscribe {
  const t = tauri()
  if (!t) return noop
  let done = false
  let unlisten: (() => void) | null = null
  t.event
    .listen<T>(name, (e) => {
      if (!done) cb(e.payload)
    })
    .then(
      (fn) => {
        if (done) fn()
        else unlisten = fn
      },
      (err: unknown) => console.warn(`[syn-desktop] listen ${name} failed`, err),
    )
  return () => {
    done = true
    unlisten?.()
    unlisten = null
  }
}

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T | null> {
  const t = tauri()
  if (!t) return null
  return t.core.invoke<T>(cmd, args)
}

// ------------------------------------------------------------------ events

/** Cmd/Ctrl+K (global shortcut, View menu or tray): open the Command palette. */
export function onCommandPalette(cb: () => void): Unsubscribe {
  return on<null>(EVENTS.commandPalette, () => cb())
}

/** Go menu items and syn137:// deep links. `path` is an app route such as "/executions/abc". */
export function onNavigate(cb: (path: string) => void): Unsubscribe {
  return on<{ path: string }>(EVENTS.navigate, (p) => {
    if (p && typeof p.path === 'string' && p.path.startsWith('/')) cb(p.path)
  })
}

/** "Settings…" in the app menu (Cmd/Ctrl+,). */
export function onOpenSettings(cb: () => void): Unsubscribe {
  return on<null>(EVENTS.openSettings, () => cb())
}

export function onSettingsChanged(cb: (settings: DesktopSettings) => void): Unsubscribe {
  return on<DesktopSettings>(EVENTS.settingsChanged, cb)
}

// ------------------------------------------------------------------ commands

/** Report the live connection state; the tray dot follows it. No-op on the web. */
export async function setLiveState(state: LiveState): Promise<void> {
  await call<null>('set_live_state', { state })
}

export function getSettings(): Promise<DesktopSettings | null> {
  return call<DesktopSettings>('get_settings')
}

/**
 * Save the API root (null or "" restores the default). Rejects with the
 * shell's message when the URL is not an absolute http(s) URL.
 */
export function setApiBaseUrl(url: string | null): Promise<DesktopSettings | null> {
  return call<DesktopSettings>('set_api_base_url', { url })
}

/** Change the global palette shortcut ("" disables it). Rejects if the OS refuses it. */
export function setGlobalShortcut(shortcut: string): Promise<DesktopSettings | null> {
  return call<DesktopSettings>('set_global_shortcut', { shortcut })
}

/**
 * Tell the shell the page is listening. Resolves to a route that arrived
 * before then (a deep link that launched the app), at most once.
 */
export function desktopReady(): Promise<string | null> {
  return call<string | null>('desktop_ready')
}

/**
 * The API root the web client should use: the saved setting, else the
 * client's own default under the vite dev server (its proxy serves /api/v1),
 * else the local API. Returns null for "keep the client's default".
 */
export function effectiveApiBaseUrl(
  settings: DesktopSettings | null,
  location: { port: string } | undefined = (globalThis as { location?: { port: string } }).location,
): string | null {
  if (settings?.apiBaseUrl) return settings.apiBaseUrl
  if (!settings) return null
  return location?.port === DEV_SERVER_PORT ? null : DEFAULT_DESKTOP_API_BASE_URL
}

// ------------------------------------------------------------------ wiring

export interface DesktopHooks {
  navigate: (path: string) => void
  openCommandPalette: () => void
  openSettings?: () => void
  /** Called with the API root to use (null: keep the client default), now and on every change. */
  configureApi?: (baseUrl: string | null) => void
}

/**
 * Wire every shell event to the app and apply the saved settings. Resolves
 * to an unsubscribe. Outside the desktop app it does nothing.
 *
 * Call it before the first API request so `configureApi` runs first: the
 * returned promise resolves after the settings are applied.
 */
export async function startDesktop(hooks: DesktopHooks): Promise<Unsubscribe> {
  if (!isDesktop()) return noop
  const subs: Unsubscribe[] = [
    onCommandPalette(hooks.openCommandPalette),
    onNavigate(hooks.navigate),
    onSettingsChanged((s) => hooks.configureApi?.(effectiveApiBaseUrl(s))),
  ]
  if (hooks.openSettings) subs.push(onOpenSettings(hooks.openSettings))

  try {
    hooks.configureApi?.(effectiveApiBaseUrl(await getSettings()))
  } catch (err) {
    console.warn('[syn-desktop] could not read settings', err)
  }
  try {
    const pending = await desktopReady()
    if (pending) hooks.navigate(pending)
  } catch (err) {
    console.warn('[syn-desktop] desktop_ready failed', err)
  }
  return () => subs.forEach((u) => u())
}
