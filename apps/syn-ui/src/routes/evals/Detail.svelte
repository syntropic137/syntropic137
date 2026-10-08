<!-- STUB. Owner: Eval screen agent. Boards: Eval · PhoneEval. -->
<script lang="ts">
  import { getEval, listEvalRuns } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import { setPage } from '../../lib/page.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params }: PageProps = $props()
  const ev = resource((signal) => getEval(params.evalId ?? '', signal))
  const runs = resource((signal) => listEvalRuns(params.evalId ?? '', {}, signal))

  $effect(() => {
    if (ev.data) setPage({ title: ev.data.name, crumbs: [{ label: 'Evals', href: '/evals' }, { label: ev.data.name }] })
  })
</script>

<StubPage
  title={ev.data?.name ?? 'Eval'}
  boards="Eval · PhoneEval"
  loading={ev.loading}
  error={ev.error}
  facts={ev.data ? [['Runs', runs.data?.total ?? '…'], ['Pass rate', ev.data.pass_rate_display]] : []}
/>
