<!-- STUB. Owner: Overview screen agent. Boards: Main (Overview), PhoneOverview, UsageMeter. -->
<script lang="ts">
  import { formatCost, formatTokens } from '@syn137/skyline-core/format'
  import { getContributionHeatmap, getMetrics } from '@syn137/syn-ui-data'
  import { resource } from '../../lib/load.svelte'
  import type { PageProps } from '../../lib/routes'
  import StubPage from '../../shell/StubPage.svelte'

  let { params: _params }: PageProps = $props()
  const metrics = resource((signal) => getMetrics(undefined, signal), { live: (t) => t.startsWith('workflow_') })
  const heatmap = resource((signal) => getContributionHeatmap({}, signal))
</script>

<StubPage
  title="All quiet."
  boards="Main (Overview) · PhoneOverview"
  loading={metrics.loading}
  error={metrics.error ?? heatmap.error}
  facts={metrics.data
    ? [
        ['Runs', metrics.data.total_workflows],
        ['Tokens', formatTokens(metrics.data.total_tokens)],
        ['Spend', formatCost(metrics.data.total_cost_usd)],
        ['Active days', heatmap.data?.days?.length ?? '…'],
      ]
    : []}
/>
