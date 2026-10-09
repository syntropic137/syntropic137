/**
 * Command palette view-model (CompNav "command · ⌘K"). Plain items the
 * app renders through the Command component; filtering is commandFilter's.
 * Go-to hints come from the keymap, so the palette shows the same `G E`
 * the handler answers to.
 */
import { commandScore, filterCommandGroups, type CommandFilterItem } from '../../state/commandFilter'
import { shortcutFor, type KeymapSection } from '../../state/keymap'

export type PaletteCommand = 'run-workflow' | 'copy-page' | 'shortcuts'

export type PaletteTarget = { kind: 'href'; href: string } | { kind: 'external'; url: string } | { kind: 'command'; command: PaletteCommand }

export interface PaletteItem extends CommandFilterItem {
  id: string
  meta?: string
  shortcut?: string
  target: PaletteTarget
}

export interface PaletteGroup {
  heading: string
  items: PaletteItem[]
}

export interface PaletteSection {
  key: KeymapSection
  label: string
  href: string
}

export interface PaletteRecent {
  id: string
  label: string
  meta?: string
  status?: string
}

export interface HelpLinks {
  docs: string
  featureRequests: string
  issues: string
}

export interface PaletteInput {
  sections: readonly PaletteSection[]
  executions?: readonly PaletteRecent[]
  sessions?: readonly PaletteRecent[]
  workflows?: readonly PaletteRecent[]
  help: HelpLinks
  /** Show ⌘ (Apple) or Ctrl in key hints. */
  apple?: boolean
  /** How many recent rows per kind. */
  recent?: number
}

const recentItems = (kind: string, base: string, rows: readonly PaletteRecent[] | undefined, n: number): PaletteItem[] =>
  (rows ?? []).slice(0, n).map((r) => ({
    id: `${kind}-${r.id}`,
    label: r.label,
    meta: r.meta ?? r.id.slice(0, 8),
    keywords: [r.id, kind, ...(r.status ? [r.status] : [])],
    target: { kind: 'href', href: `${base}/${encodeURIComponent(r.id)}` },
  }))

/** The palette's groups, in board order: recent objects, actions, go to, help. Empty groups are dropped. */
export function buildPalette(input: PaletteInput): PaletteGroup[] {
  const apple = input.apple ?? true
  const n = input.recent ?? 5
  const groups: PaletteGroup[] = [
    { heading: 'Recent executions', items: recentItems('execution', '/executions', input.executions, n) },
    { heading: 'Recent sessions', items: recentItems('session', '/sessions', input.sessions, n) },
    { heading: 'Workflows', items: recentItems('workflow', '/workflows', input.workflows, n) },
    {
      heading: 'Actions',
      items: [
        { id: 'act-run', label: 'Run workflow', keywords: ['start', 'execute', 'new run'], target: { kind: 'command', command: 'run-workflow' } },
        { id: 'act-copy', label: 'Copy page for an agent', keywords: ['clipboard', 'prompt', 'llm'], target: { kind: 'command', command: 'copy-page' } },
      ],
    },
    {
      heading: 'Go to',
      items: input.sections.map((s) => ({
        id: `go-${s.key}`,
        label: s.label,
        keywords: ['go', 'navigate', s.key],
        shortcut: shortcutFor({ type: 'goto', section: s.key }, apple),
        target: { kind: 'href', href: s.href },
      })),
    },
    {
      heading: 'Help',
      items: [
        { id: 'help-keys', label: 'Keyboard shortcuts', keywords: ['help', 'keys', 'hotkeys'], shortcut: shortcutFor({ type: 'help' }, apple), target: { kind: 'command', command: 'shortcuts' } },
        { id: 'help-docs', label: 'Documentation', keywords: ['help', 'docs', 'guide'], target: { kind: 'external', url: input.help.docs } },
        { id: 'help-feature', label: 'Request a feature', keywords: ['help', 'feedback', 'idea', 'canny'], target: { kind: 'external', url: input.help.featureRequests } },
        { id: 'help-issue', label: 'Report an issue', keywords: ['help', 'bug', 'github', 'issues'], target: { kind: 'external', url: input.help.issues } },
      ],
    },
  ]
  return groups.filter((g) => g.items.length > 0)
}

/**
 * Filter with commandFilter, then put the group holding the best match
 * first, so Enter on "exec" opens Executions rather than the first group
 * that merely mentions it. Ties keep board order.
 */
export function filterPalette(groups: readonly PaletteGroup[], query: string): PaletteGroup[] {
  const shown = filterCommandGroups(groups, query).map((g) => ({ heading: g.heading ?? '', items: [...g.items] }))
  if (!query.trim()) return shown
  const best = (g: PaletteGroup) => Math.max(...g.items.map((i) => commandScore(query, i)))
  return shown.map((g, i) => ({ g, i, s: best(g) })).sort((a, b) => b.s - a.s || a.i - b.i).map((x) => x.g)
}

export interface PageSnapshot {
  title: string
  url: string
  crumbs: readonly string[]
  /** The page's visible text. */
  text: string
}

export const PAGE_TEXT_LIMIT = 12_000

/** "Copy page for an agent": the page's title, URL, trail and text as one plain block. */
export function pageForAgent(page: PageSnapshot, limit = PAGE_TEXT_LIMIT): string {
  const text = page.text
    .split('\n')
    .map((l) => l.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join('\n')
  const clipped = text.length > limit ? `${text.slice(0, limit)}\n[truncated at ${limit} characters]` : text
  const trail = page.crumbs.length ? `\nTrail: ${page.crumbs.join(' / ')}` : ''
  return `Syntropic137 page: ${page.title || 'Untitled'}\nURL: ${page.url}${trail}\n\n${clipped}\n`
}
