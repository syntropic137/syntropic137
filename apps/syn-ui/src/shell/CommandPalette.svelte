<!--
  The ⌘K Command palette (CompNav "command · ⌘K"). A lazy chunk, mounted
  while open. Recent rows come from the same cached list reads Overview
  makes (no extra request when Overview has run), so opening it is instant.
-->
<script lang="ts">
  import { listExecutions, listSessions, listWorkflows } from '@syn137/syn-ui-data'
  import { buildPalette, filterPalette, pageForAgent, type PaletteCommand, type PaletteItem } from '@syn137/skyline-core/screens/palette'
  import { CommandDialog, type CommandGroup } from '@syn137/skyline-svelte-v5'
  import { HELP_LINKS } from '../lib/links'
  import { resource } from '../lib/load.svelte'
  import { page } from '../lib/page.svelte'
  import { href, router } from '../lib/router'
  import { SECTIONS } from './nav'
  import { APPLE, overlays } from './overlays.svelte'

  /** Overview's own reads, so the palette shares their cache entries. */
  const executions = resource((signal) => listExecutions({ page: 1, page_size: 6 }, signal))
  const workflows = resource((signal) => listWorkflows({ page_size: 100 }, signal))
  const sessions = resource((signal) => listSessions({ page: 1, page_size: 6 }, signal))

  let search = $state('')

  const all = $derived(
    buildPalette({
      sections: SECTIONS,
      apple: APPLE,
      help: HELP_LINKS,
      executions: executions.data?.executions.map((e) => ({
        id: e.workflow_execution_id,
        label: e.workflow_name,
        meta: `${e.status} · ${e.workflow_execution_id.slice(0, 8)}`,
        status: e.status,
      })),
      sessions: sessions.data?.sessions?.map((s) => ({
        id: s.id,
        label: s.workflow_name ?? s.phase_display ?? 'Session',
        meta: `${s.phase_display ?? s.status} · ${s.id.slice(0, 8)}`,
        status: s.status,
      })),
      workflows: workflows.data?.workflows.map((w) => ({ id: w.id, label: w.name, meta: w.id })),
    }),
  )

  async function copyPage() {
    const main = document.getElementById('sky-main')
    const text = pageForAgent({
      title: page.title || document.title,
      url: location.href,
      crumbs: page.crumbs.map((c) => c.label),
      text: main?.innerText ?? '',
    })
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // Clipboard refused (permissions, insecure origin): nothing to recover.
    }
  }

  const COMMANDS: Record<PaletteCommand, () => void> = {
    'run-workflow': () => router.navigate(href('/workflows')),
    'copy-page': () => void copyPage(),
    shortcuts: () => overlays.openShortcuts(),
  }

  function toItem(item: PaletteItem) {
    const t = item.target
    return {
      ...item,
      href: t.kind === 'href' ? t.href : undefined,
      onSelect: t.kind === 'external' ? () => void window.open(t.url, '_blank', 'noopener') : t.kind === 'command' ? COMMANDS[t.command] : undefined,
    }
  }

  const groups: CommandGroup[] = $derived(filterPalette(all, search).map((g) => ({ heading: g.heading, items: g.items.map(toItem) })))
</script>

<CommandDialog
  bind:open={overlays.palette}
  bind:search
  {groups}
  shouldFilter={false}
  loading={executions.loading && !executions.data}
  aria-label="Command palette"
  placeholder="Search or jump to…"
  onNavigate={(to) => router.navigate(href(to))}
/>
