<!--
  <sky-harness-lanes>: Harness Lanes as a custom element (options in
  ./options.ts). Set `phases` ({ name, provider, span }[]) as a JS property
  or a JSON attribute.
-->
<script lang="ts">
  import type { HarnessLanesProps } from '@syn137/skyline-core/patterns'
  import HarnessLanes from '../patterns/HarnessLanes/HarnessLanes.svelte'
  import { hostAttachment } from './host'

  let { phases = [], label }: Partial<HarnessLanesProps> = $props()

  const connect = hostAttachment(undefined, { block: true })
</script>

<HarnessLanes {phases} {label} {@attach connect} />
