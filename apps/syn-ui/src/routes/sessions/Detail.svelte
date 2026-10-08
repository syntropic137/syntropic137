<!-- STUB. Owner: Session screen agent. Boards: Session · PhoneSession · UsageMeter. -->
<script lang="ts">
  import { formatCost, formatTokens, shortId } from '@syn137/skyline-core/format'
  import { getSession } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params }: PageProps = $props()
  const session = resource((signal) => getSession(params.sessionId ?? '', signal))

  $effect(() => {
    const s = session.data
    if (!s) return
    const crumbs = s.execution_id
      ? [
          { label: 'Executions', href: '/executions' },
          { label: 'Execution', id: shortId(s.execution_id), href: `/executions/${s.execution_id}` },
          { label: 'Session', id: shortId(s.id) },
        ]
      : [{ label: 'Sessions', href: '/sessions' }, { label: 'Session', id: shortId(s.id) }]
    setPage({ title: `Session ${shortId(s.id)}`, crumbs })
  })
</script>

<StubPage
  title={session.data?.phase_display ?? 'Session'}
  boards="Session · PhoneSession"
  loading={session.loading}
  error={session.error}
  facts={session.data
    ? [
        ['Operations', session.data.operations.length],
        ['Tokens', formatTokens(session.data.total_tokens)],
        ['Cost', formatCost(session.data.total_cost_usd)],
      ]
    : []}
/>
