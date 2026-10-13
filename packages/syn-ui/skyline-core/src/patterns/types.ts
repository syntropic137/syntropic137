/**
 * Prop types for the 22 Skyline patterns. Plain data, no framework types, so
 * the Svelte patterns, a custom-element build or a Tauri shell share them.
 *
 * Phase agents: add each pattern's props here (or in a sibling file
 * re-exported from ./index.ts) BEFORE building its Svelte component.
 */

/** One step of a Breadcrumb Trail. The last crumb is the current page. */
export interface Crumb {
  label: string
  /** Mono suffix, e.g. a short ID: "Execution 66e14f23". */
  id?: string
  /** Omit on the current page. */
  href?: string
}

/** A destination in the App Shell (capsule on desktop, dock and More on phone). */
export interface NavItem {
  key: string
  label: string
  href: string
  /** Optional count shown in the More sheet. */
  count?: number
}

/** The six objects that get a 3D Object Icon. */
export type ObjectKind = 'trigger' | 'workflow' | 'execution' | 'session' | 'artifact' | 'eval'

/** Live connection state for the shell's Live indicator. */
export type LiveState = 'live' | 'connecting' | 'offline' | 'fixtures'
