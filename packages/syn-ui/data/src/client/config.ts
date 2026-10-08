/**
 * Client configuration. The app calls configureClient() once at startup:
 *
 *   configureClient({ fixtures: import.meta.env.VITE_SYN_FIXTURES === '1' })
 *
 * This package never reads import.meta.env itself, so it runs unchanged in
 * Node (tests, CLI, Tauri) and in any bundler.
 */
export const API_BASE = '/api/v1'

export interface ClientConfig {
  /** Prefix for every request path. Default "/api/v1" (the dev proxy and nginx route it). */
  baseUrl: string
  /** Serve every request from in-memory fixtures instead of the network. */
  fixtures: boolean
  /** Simulated latency for fixture responses, ms (default 120; 0 in tests). */
  fixtureLatencyMs: number
  /** fetch implementation (default globalThis.fetch). */
  fetch: typeof fetch
}

let current: ClientConfig = {
  baseUrl: API_BASE,
  fixtures: false,
  fixtureLatencyMs: 120,
  fetch: (...args) => globalThis.fetch(...args),
}

export function configureClient(partial: Partial<ClientConfig>): ClientConfig {
  current = { ...current, ...partial }
  return current
}

export function clientConfig(): Readonly<ClientConfig> {
  return current
}

/** True when fixtures mode is on. */
export function usingFixtures(): boolean {
  return current.fixtures
}
