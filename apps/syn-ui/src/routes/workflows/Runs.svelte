<!-- STUB. Owner: Workflow screen agent. Reuses the Executions list, filtered to one workflow. -->
<script lang="ts">
  import { getWorkflow, listWorkflowRuns } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params }: PageProps = $props()
  const wf = resource((signal) => getWorkflow(params.workflowId ?? '', signal))
  const runs = resource((signal) => listWorkflowRuns(params.workflowId ?? '', signal))

  $effect(() => {
    if (wf.data)
      setPage({
        title: `${wf.data.name} runs`,
        crumbs: [{ label: 'Workflows', href: '/workflows' }, { label: wf.data.name, href: `/workflows/${wf.data.id}` }, { label: 'Runs' }],
      })
  })
</script>

<StubPage title="Runs" boards="Executions (filtered)" loading={runs.loading} error={runs.error} facts={runs.data ? [['Runs', runs.data.length]] : []} />
