<!-- <sky-harness-chip>: Harness Chip as a custom element (options in ./options.ts). -->
<script lang="ts">
  import type { HarnessChipProps } from '@syn137/skyline-core/patterns'
  import HarnessChip from '../patterns/HarnessChip/HarnessChip.svelte'
  import { hostAttachment } from './host'

  let { provider = '', label }: Partial<HarnessChipProps> = $props()

  const connect = hostAttachment()
</script>

<HarnessChip {provider} {label} {@attach connect} />
