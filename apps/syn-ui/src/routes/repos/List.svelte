<!-- STUB. Owner: Repos screen agent. Boards: none yet (spec phase 4; card list). -->
<script lang="ts">
  import { listRepos } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params: _params }: PageProps = $props()
  const list = resource((signal) => listRepos(signal))
</script>

<StubPage title="Repos" boards="none yet (spec phase 4; card list)" loading={list.loading} error={list.error} facts={list.data ? [['Total', list.data.length]] : []} />
