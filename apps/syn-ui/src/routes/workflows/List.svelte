<!-- STUB. Owner: Workflows screen agent. Boards: Workflows · PhoneWorkflows. -->
<script lang="ts">
  import { listWorkflows } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params: _params }: PageProps = $props()
  const list = resource((signal) => listWorkflows({}, signal))
</script>

<StubPage title="Workflows" boards="Workflows · PhoneWorkflows" loading={list.loading} error={list.error} facts={list.data ? [['Total', list.data.total]] : []} />
