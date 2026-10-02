/**
 * Replays the API-generated parity fixture as a fake server that honours `limit`.
 *
 * Each recorded section (per filter set) is reassembled from its recorded pages
 * by following the recorded cursors, then re-served in slices of exactly the
 * requested `limit` with this replay's own opaque cursors. A client that
 * over-reads or trusts a page size is therefore caught. Status and node lookups
 * are served as recorded; `patchStatus` lets a test vary the summary.
 */
import fixtureJson from '../../../../syn-api/tests/fixtures/session_inventory_parity.json'

export interface Exchange { path: string; query: Record<string, string>; status: number; body: unknown }
export interface ParityFixture {
  execution_id: string
  phase_filter: string
  exchanges: Exchange[]
  expected: Record<string, unknown>
  expected_phase: { node_ids: string[]; cross_page_child: string }
}

export const fixture = fixtureJson as unknown as ParityFixture

interface RecordedPage { items: unknown[]; item_keys: unknown[]; next_cursor: string | null; [field: string]: unknown }
interface Section { template: RecordedPage; items: unknown[]; item_keys: unknown[] }

const CURSOR_PREFIX = 'replay:'

function queryKey(path: string, query: Record<string, string>): string {
  return JSON.stringify([path, Object.entries(query).sort()])
}

function withoutCursor(query: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(query).filter(([name]) => name !== 'cursor'))
}

function assemble(path: string, filters: Record<string, string>): Section {
  const find = (cursor: string | null) => fixture.exchanges.find(exchange => queryKey(exchange.path, exchange.query)
    === queryKey(path, cursor === null ? filters : { ...filters, cursor }))
  let exchange = find(null)
  const template = exchange!.body as RecordedPage
  const section: Section = { template, items: [], item_keys: [] }
  while (exchange) {
    const page = exchange.body as RecordedPage
    section.items.push(...page.items)
    section.item_keys.push(...page.item_keys)
    exchange = page.next_cursor === null ? undefined : find(page.next_cursor)
  }
  return section
}

const isPage = (exchange: Exchange) => /\/session-inventory\/[^/]+\/[a-z]+$/.test(exchange.path)

function buildSections(): Map<string, Section> {
  const sections = new Map<string, Section>()
  for (const exchange of fixture.exchanges.filter(isPage)) {
    const filters = withoutCursor(exchange.query)
    const key = queryKey(exchange.path, filters)
    if (!sections.has(key)) sections.set(key, assemble(exchange.path, filters))
  }
  return sections
}

const sections = buildSections()

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function servePage(section: Section, query: Record<string, string>, limit: number): Response {
  const cursor = query['cursor']
  if (cursor !== undefined && !cursor.startsWith(CURSOR_PREFIX)) return json({ detail: { code: 'cursor_invalid', message: 'foreign cursor', restart: true } }, 400)
  const offset = cursor === undefined ? 0 : Number(cursor.slice(CURSOR_PREFIX.length))
  const end = offset + limit
  return json({
    ...section.template,
    items: section.items.slice(offset, end),
    item_keys: section.item_keys.slice(offset, end),
    next_cursor: end < section.items.length ? `${CURSOR_PREFIX}${end}` : null,
  })
}

export type StatusPatch = (status: Record<string, unknown>) => Record<string, unknown>

/** A fetch implementation over the fixture. `requests` records every page limit asked for. */
export function createReplay(patchStatus: StatusPatch = status => status) {
  const limits: number[] = []
  async function fetchReplay(input: RequestInfo | URL): Promise<Response> {
    const url = new URL(String(input), 'http://dashboard.test')
    const path = url.pathname.replace(/^\/api\/v1/, '')
    const query = Object.fromEntries([...url.searchParams].filter(([name]) => name !== 'limit'))
    const section = sections.get(queryKey(path, withoutCursor(query)))
    if (section) {
      const limit = Number(url.searchParams.get('limit') ?? '100')
      limits.push(limit)
      return servePage(section, query, limit)
    }
    const recorded = fixture.exchanges.find(exchange => queryKey(exchange.path, exchange.query) === queryKey(path, query))
    if (!recorded) return json({ detail: `unrecorded ${path}` }, 404)
    const isStatus = path === `/executions/${fixture.execution_id}/session-inventory`
    return json(isStatus ? patchStatus(recorded.body as Record<string, unknown>) : recorded.body, recorded.status)
  }
  return { fetch: fetchReplay, limits }
}
