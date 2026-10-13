// HELPER: planted route builder
export interface FixtureRoute {
  method: string
  path: string
  handle: () => unknown
}
export function route(method: string, path: string, handle: () => unknown): FixtureRoute {
  return { method, path, handle }
}
