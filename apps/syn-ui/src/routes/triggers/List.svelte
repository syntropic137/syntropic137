<!-- STUB. Owner: Triggers screen agent. Boards: Triggers · PhoneTriggers. -->
<script lang="ts">
  import { listTriggers } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params: _params }: PageProps = $props()
  const list = resource((signal) => listTriggers({}, signal))
</script>

<StubPage title="Triggers" boards="Triggers · PhoneTriggers" loading={list.loading} error={list.error} facts={list.data ? [['Total', list.data.total]] : []} />
