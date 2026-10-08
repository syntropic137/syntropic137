<!-- STUB. Owner: Triggers screen agent. Boards: Triggers · PhoneTriggers (rules open in place). -->
<script lang="ts">
  import { getTrigger } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params }: PageProps = $props()
  const trig = resource((signal) => getTrigger(params.triggerId ?? '', signal))

  $effect(() => {
    if (trig.data) setPage({ title: trig.data.name, crumbs: [{ label: 'Triggers', href: '/triggers' }, { label: trig.data.name }] })
  })
</script>

<StubPage
  title={trig.data?.name ?? 'Trigger'}
  boards="Triggers · PhoneTriggers"
  loading={trig.loading}
  error={trig.error}
  facts={trig.data ? [['Status', trig.data.status], ['Fired', trig.data.fire_count]] : []}
/>
