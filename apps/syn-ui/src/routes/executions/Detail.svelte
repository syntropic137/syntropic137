<!-- STUB. Owner: Execution screen agent. Boards: Execution · PhoneExecution · PhaseKit · UsageMeter. -->
<script lang="ts">
  import { formatCost, formatTokens, shortId } from '@syn137/skyline-core/format'
  import { getExecution } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params }: PageProps = $props()
  const exec = resource((signal) => getExecution(params.executionId ?? '', signal), {
    live: (t) => t.startsWith('phase_') || t.startsWith('workflow_'),
  })

  $effect(() => {
    const d = exec.data
    if (d)
      setPage({
        title: `${d.workflow_name} ${shortId(d.workflow_execution_id)}`,
        crumbs: [
          { label: 'Workflows', href: '/workflows' },
          { label: d.workflow_name, href: `/workflows/${d.workflow_id}` },
          { label: 'Execution', id: shortId(d.workflow_execution_id) },
        ],
      })
  })
</script>

<StubPage
  title={exec.data?.workflow_name ?? 'Execution'}
  boards="Execution · PhoneExecution"
  loading={exec.loading}
  error={exec.error}
  facts={exec.data
    ? [
        ['Status', exec.data.status],
        ['Phases', `${exec.data.completed_phases} of ${exec.data.total_phases}`],
        ['Tokens', formatTokens(exec.data.total_tokens)],
        ['Cost', formatCost(exec.data.total_cost_usd)],
      ]
    : []}
/>
