<!--
  <sky-usage-band>: Usage Band as a custom element (options in
  ./options.ts). Set `tokens` ({ cacheRead, cacheWrite, output, input }) as
  a JS property or a JSON attribute. Renders nothing until `tokens` is set.
  Style the bar from outside with ::part(band) and ::part(legend).
-->
<script lang="ts">
  import UsageBand from '../patterns/UsageBand/UsageBand.svelte'
  import type { UsageBandProps } from '../patterns/UsageBand/types'
  import { hostAttachment } from './host'

  let { tokens, rates, shape, legend }: Partial<Pick<UsageBandProps, 'tokens' | 'rates' | 'shape' | 'legend'>> = $props()

  const connect = hostAttachment(undefined, { block: true })
</script>

{#if tokens}
  <UsageBand {tokens} {rates} {shape} {legend} {@attach connect} />
{/if}
