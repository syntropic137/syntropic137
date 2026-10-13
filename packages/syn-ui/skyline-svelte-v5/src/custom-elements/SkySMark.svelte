<!--
  <sky-s-mark>: the S Mark as a custom element (options in ./options.ts).
  `size` is a pixel number or a CSS length ("15%"); `animate` drops the
  cubes in; `label=""` makes it decorative. Light-DOM children are a
  fallback that shows until the element upgrades (no slot renders them).
-->
<script lang="ts">
  import type { SMarkProps } from '@syn137/skyline-core/patterns'
  import SMark from '../patterns/SMark/SMark.svelte'
  import { hostAttachment } from './host'

  let { size, animate = false, label = 'Syntropic137' }: SMarkProps = $props()

  const connect = hostAttachment(undefined, { block: true, motion: true })
</script>

<SMark {size} {animate} {label} {@attach connect} />
