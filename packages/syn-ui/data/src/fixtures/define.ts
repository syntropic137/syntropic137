/**
 * Building blocks for fixture routes. Kept apart from router.ts so resource
 * fixture files can import them without a cycle through routes.ts.
 */
import { ApiError } from '../client/errors'
import type { HttpMethod } from '../client/http'

export interface FixtureRequest {
  method: HttpMethod
  path: string
  /** Named path params, decoded: "/workflows/:workflowId" -> { workflowId }. */
  params: Record<string, string>
  query: URLSearchParams
  body: unknown
}

export type FixtureHandler = (req: FixtureRequest) => unknown

export interface FixtureRoute {
  method: HttpMethod
  /** Path relative to the API base, with :params. */
  path: string
  handle: FixtureHandler
}

/** Declare a fixture route: route('GET', '/workflows/:workflowId', ({ params }) => ...). */
export function route(method: HttpMethod, path: string, handle: FixtureHandler): FixtureRoute {
  return { method, path, handle }
}

/** Throw the API's 404 shape from inside a handler. */
export function notFound(what: string): never {
  throw new ApiError(404, `${what} not found`)
}
