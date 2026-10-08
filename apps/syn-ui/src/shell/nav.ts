import type { NavItem } from '@syn137/skyline-core/patterns'
import type { Area } from '../lib/routes'

export type NavKey = Exclude<Area, 'none'>

export interface Section extends NavItem {
  key: NavKey
}

/** The eight sections, in capsule order (TopNav board). */
export const SECTIONS: Section[] = [
  { key: 'overview', label: 'Overview', href: '/' },
  { key: 'workflows', label: 'Workflows', href: '/workflows' },
  { key: 'executions', label: 'Executions', href: '/executions' },
  { key: 'evals', label: 'Evals', href: '/evals' },
  { key: 'sessions', label: 'Sessions', href: '/sessions' },
  { key: 'artifacts', label: 'Artifacts', href: '/artifacts' },
  { key: 'triggers', label: 'Triggers', href: '/triggers' },
  { key: 'repos', label: 'Repos', href: '/repos' },
]

/**
 * Phone dock: four destinations plus More (spec, Platforms: Overview and
 * Executions keep their slots, Evals joins, the fourth slot is Workflows
 * until it is named).
 */
export const DOCK_KEYS: NavKey[] = ['overview', 'executions', 'evals', 'workflows']

export const DOCK: Section[] = DOCK_KEYS.map((k) => SECTIONS.find((s) => s.key === k)!)

/** Everything else lives behind More. */
export const MORE: Section[] = SECTIONS.filter((s) => !DOCK_KEYS.includes(s.key))
