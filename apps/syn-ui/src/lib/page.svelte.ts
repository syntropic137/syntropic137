/**
 * Per-page shell metadata: the breadcrumb trail and the document title.
 *
 * The app resets both to the route's defaults (lib/routes.ts) whenever the
 * page changes. A page refines them once it knows real names:
 *
 *   const wf = resource((signal) => getWorkflow(params.workflowId, signal))
 *   $effect(() => {
 *     if (wf.data) setPage({ title: wf.data.name, crumbs: [
 *       { label: 'Workflows', href: '/workflows' },
 *       { label: wf.data.name },
 *     ] })
 *   })
 */
import type { Crumb } from '@syn137/skyline-core/patterns'

class PageMeta {
  crumbs = $state<Crumb[]>([])
  title = $state('')
}

export const page = new PageMeta()

export function setPage(meta: { title?: string; crumbs?: Crumb[] }): void {
  if (meta.title !== undefined) page.title = meta.title
  if (meta.crumbs !== undefined) page.crumbs = meta.crumbs
}
