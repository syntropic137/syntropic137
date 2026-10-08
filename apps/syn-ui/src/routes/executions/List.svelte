<!-- STUB. Owner: Executions screen agent. Boards: Executions · PhoneExecutions. -->
<script lang="ts">
  import { listExecutions } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params: _params }: PageProps = $props()
  const list = resource((signal) => listExecutions({ page: 1, page_size: 50 }, signal))
</script>

<StubPage title="Executions" boards="Executions · PhoneExecutions" loading={list.loading} error={list.error} facts={list.data ? [['Total', list.data.total]] : []} />
