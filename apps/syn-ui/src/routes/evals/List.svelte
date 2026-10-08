<!-- STUB. Owner: Evals screen agent. Boards: Evals · PhoneEvals. -->
<script lang="ts">
  import { listEvals } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params: _params }: PageProps = $props()
  const list = resource((signal) => listEvals({}, signal))
</script>

<StubPage title="Evals" boards="Evals · PhoneEvals" loading={list.loading} error={list.error} facts={list.data ? [['Total', list.data.total]] : []} />
