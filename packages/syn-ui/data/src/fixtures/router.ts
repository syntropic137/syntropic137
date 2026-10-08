/**
 * Fixtures router: answers client requests from in-memory data when the
 * client runs with `fixtures: true` (VITE_SYN_FIXTURES=1 in the app).
 *
 * Loaded with a dynamic import from client/http.ts, so none of this ships
 * in a production first load.
 */
import { ApiError } from '../client/errors'
import type { HttpMethod } from '../client/http'
import type { FixtureRoute } from './define'
import { routes } from './routes'

export { route, notFound } from './define'
export type { FixtureRequest, FixtureHandler, FixtureRoute } from './define'

interface Compiled {
  route: FixtureRoute
  regex: RegExp
  names: string[]
}

let compiled: Compiled[] | null = null

function compile(list: readonly FixtureRoute[]): Compiled[] {
  return list.map((r) => {
    const names: string[] = []
    const source = r.path
      .split('/')
      .map((part) => {
        if (part.startsWith(':')) {
          names.push(part.slice(1))
          return '([^/]+)'
        }
        return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      })
      .join('/')
    return { route: r, regex: new RegExp(`^${source}/?$`), names }
  })
}

export function matchFixture(method: HttpMethod, path: string): { route: FixtureRoute; params: Record<string, string> } | null {
  compiled ??= compile(routes)
  for (const c of compiled) {
    if (c.route.method !== method) continue
    const m = c.regex.exec(path)
    if (!m) continue
    const params: Record<string, string> = {}
    c.names.forEach((name, i) => {
      params[name] = decodeURIComponent(m[i + 1] ?? '')
    })
    return { route: c.route, params }
  }
  return null
}

/** Resolve a request against the fixture routes; 404 ApiError when none matches. */
export async function resolveFixture(method: HttpMethod, path: string, query: URLSearchParams, body: unknown): Promise<unknown> {
  const hit = matchFixture(method, path)
  if (!hit) throw new ApiError(404, `No fixture for ${method} ${path}`)
  return hit.route.handle({ method, path, params: hit.params, query, body })
}

