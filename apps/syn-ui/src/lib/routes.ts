/**
 * Every route the app serves. Paths match apps/syn-dashboard-ui/src/App.tsx
 * (minus /insights, which redirects to Overview), so swapping /next for /
 * is the only change a link needs.
 *
 * Each page is its own lazily loaded chunk. The `crumbs` here are the
 * defaults shown while a page loads; a page refines them with setPage()
 * once it knows names (see lib/page.svelte.ts).
 */
import type { Component } from 'svelte'
import type { Crumb } from '@syn137/skyline-core/patterns'
import type { Params } from './router/match'

/** Primary sections; drives the nav highlight. */
export type Area = 'overview' | 'workflows' | 'executions' | 'evals' | 'sessions' | 'artifacts' | 'triggers' | 'repos' | 'none'

export interface PageProps {
  params: Params
}

export type PageModule = { default: Component<PageProps> }

export interface RouteDef {
  path: string
  area: Area
  /** Document title before the page sets its own. */
  title: (p: Params) => string
  /** Default breadcrumb trail. Overview has none. */
  crumbs: (p: Params) => Crumb[]
  load?: () => Promise<PageModule>
  /** Redirect target instead of a page. */
  redirect?: string
}

const short = (id: string | undefined) => (id ?? '').slice(0, 8)
const list = (label: string, href: string) => (): Crumb[] => [{ label, href }]

export const routes: RouteDef[] = [
  { path: '/', area: 'overview', title: () => 'Overview', crumbs: () => [], load: () => import('../routes/overview/Overview.svelte') },

  { path: '/workflows', area: 'workflows', title: () => 'Workflows', crumbs: list('Workflows', '/workflows'), load: () => import('../routes/workflows/List.svelte') },
  {
    path: '/workflows/:workflowId',
    area: 'workflows',
    title: () => 'Workflow',
    crumbs: (p) => [{ label: 'Workflows', href: '/workflows' }, { label: 'Workflow', id: short(p.workflowId) }],
    load: () => import('../routes/workflows/Detail.svelte'),
  },
  {
    path: '/workflows/:workflowId/runs',
    area: 'workflows',
    title: () => 'Runs',
    crumbs: (p) => [
      { label: 'Workflows', href: '/workflows' },
      { label: 'Workflow', id: short(p.workflowId), href: `/workflows/${p.workflowId}` },
      { label: 'Runs' },
    ],
    load: () => import('../routes/workflows/Runs.svelte'),
  },

  { path: '/executions', area: 'executions', title: () => 'Executions', crumbs: list('Executions', '/executions'), load: () => import('../routes/executions/List.svelte') },
  {
    path: '/executions/:executionId',
    area: 'executions',
    title: () => 'Execution',
    crumbs: (p) => [{ label: 'Executions', href: '/executions' }, { label: 'Execution', id: short(p.executionId) }],
    load: () => import('../routes/executions/Detail.svelte'),
  },

  { path: '/evals', area: 'evals', title: () => 'Evals', crumbs: list('Evals', '/evals'), load: () => import('../routes/evals/List.svelte') },
  {
    path: '/evals/:evalId',
    area: 'evals',
    title: () => 'Eval',
    crumbs: (p) => [{ label: 'Evals', href: '/evals' }, { label: 'Eval', id: short(p.evalId) }],
    load: () => import('../routes/evals/Detail.svelte'),
  },

  { path: '/sessions', area: 'sessions', title: () => 'Sessions', crumbs: list('Sessions', '/sessions'), load: () => import('../routes/sessions/List.svelte') },
  {
    path: '/sessions/:sessionId',
    area: 'sessions',
    title: () => 'Session',
    crumbs: (p) => [{ label: 'Sessions', href: '/sessions' }, { label: 'Session', id: short(p.sessionId) }],
    load: () => import('../routes/sessions/Detail.svelte'),
  },

  { path: '/artifacts', area: 'artifacts', title: () => 'Artifacts', crumbs: list('Artifacts', '/artifacts'), load: () => import('../routes/artifacts/List.svelte') },
  {
    path: '/artifacts/:artifactId',
    area: 'artifacts',
    title: () => 'Artifact',
    crumbs: (p) => [{ label: 'Artifacts', href: '/artifacts' }, { label: 'Artifact', id: short(p.artifactId) }],
    load: () => import('../routes/artifacts/Detail.svelte'),
  },

  { path: '/triggers', area: 'triggers', title: () => 'Triggers', crumbs: list('Triggers', '/triggers'), load: () => import('../routes/triggers/List.svelte') },
  {
    path: '/triggers/:triggerId',
    area: 'triggers',
    title: () => 'Trigger',
    crumbs: (p) => [{ label: 'Triggers', href: '/triggers' }, { label: 'Trigger', id: short(p.triggerId) }],
    load: () => import('../routes/triggers/Detail.svelte'),
  },

  { path: '/repos', area: 'repos', title: () => 'Repos', crumbs: list('Repos', '/repos'), load: () => import('../routes/repos/List.svelte') },

  // Pattern sheet for review (not in the nav).
  { path: '/dev/patterns', area: 'none', title: () => 'Patterns', crumbs: () => [{ label: 'Dev' }, { label: 'Patterns' }], load: () => import('../routes/dev/Patterns.svelte') },

  // Insights left the nav (design review, Oct 8 2026). Old bookmarks land on Overview.
  { path: '/insights/*', area: 'overview', title: () => 'Overview', crumbs: () => [], redirect: '/' },

  // Component gallery for review (components agent). Lazy chunk; not in the nav.
  { path: '/dev/components', area: 'none', title: () => 'Components', crumbs: () => [{ label: 'Components' }], load: () => import('../routes/dev/Components.svelte') },
]

export const notFoundRoute: RouteDef = {
  path: '*',
  area: 'none',
  title: () => 'Not found',
  crumbs: () => [{ label: 'Not found' }],
  load: () => import('../routes/NotFound.svelte'),
}
