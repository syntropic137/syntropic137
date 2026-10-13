<!--
  <sky-usage-meter>: Usage Meter pattern as a custom element (options in
  ./options.ts). Set `tokens` and `costRows` as JS properties, or as JSON in
  the `tokens` / `cost-rows` attributes. Renders nothing until `tokens` is
  set. `heading` maps to the pattern's `title`, because `title` is a global
  HTML attribute on the host element.
-->
<script lang="ts">
  import UsageMeter from '../patterns/UsageMeter/UsageMeter.svelte'
  import type { UsageMeterProps } from '../patterns/UsageMeter/types'
  import { hostAttachment } from './host'

  type Props = Partial<Pick<UsageMeterProps, 'cost' | 'tokens' | 'costRows' | 'costBy' | 'note' | 'rates'>> & {
    heading?: string
  }
  let { cost, tokens, costRows = [], costBy = 'model', note, rates, heading }: Props = $props()

  const connect = hostAttachment(undefined, { block: true })
</script>

{#if tokens}
  <UsageMeter {cost} {tokens} {costRows} {costBy} {note} {rates} title={heading} {@attach connect} />
{/if}
