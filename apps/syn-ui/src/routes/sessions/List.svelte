<!-- STUB. Owner: Sessions screen agent. Boards: none yet (spec phase 4; reuse Run Row). -->
<script lang="ts">
  import { listSessions } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params: _params }: PageProps = $props()
  const list = resource((signal) => listSessions({ page: 1, page_size: 50 }, signal))
</script>

<StubPage title="Sessions" boards="none yet (spec phase 4; reuse Run Row)" loading={list.loading} error={list.error} facts={list.data ? [['Total', list.data.total]] : []} />
