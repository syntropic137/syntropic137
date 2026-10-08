<!-- STUB. Owner: Workflow screen agent. Boards: Workflow · PhoneWorkflow · PhaseKit. -->
<script lang="ts">
  import { getWorkflow } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params }: PageProps = $props()
  const wf = resource((signal) => getWorkflow(params.workflowId ?? '', signal))

  $effect(() => {
    if (wf.data) setPage({ title: wf.data.name, crumbs: [{ label: 'Workflows', href: '/workflows' }, { label: wf.data.name }] })
  })
</script>

<StubPage
  title={wf.data?.name ?? 'Workflow'}
  boards="Workflow · PhoneWorkflow"
  loading={wf.loading}
  error={wf.error}
  facts={wf.data ? [['Phases', wf.data.phases.length], ['Runs', wf.data.runs_count]] : []}
/>
