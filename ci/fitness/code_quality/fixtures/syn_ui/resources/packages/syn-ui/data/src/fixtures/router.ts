// HELPER: planted router; compiles `routes` like the real one
import type { FixtureRoute } from './define'
import { routes } from './routes'
function compile(list: readonly FixtureRoute[]): FixtureRoute[] {
  return [...list]
}
export function table(): FixtureRoute[] {
  return compile(routes)
}
