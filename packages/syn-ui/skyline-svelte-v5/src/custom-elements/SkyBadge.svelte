<!--
  <sky-badge>: Badge as a custom element (options in ./options.ts). Default
  slot is the text, slot="icon" the leading glyph.
-->
<script lang="ts">
  import Badge from '../components/Badge/Badge.svelte'
  import type { BadgeProps } from '../components/Badge/types'
  import { SLOT, hostAttachment, watchSlots } from './host'

  let { variant, tone, size, dot = false }: Pick<BadgeProps, 'variant' | 'tone' | 'size' | 'dot'> = $props()

  let hasIcon = $state(false)
  const connect = hostAttachment((host) => watchSlots(host, (s) => (hasIcon = s.has('icon'))))
</script>

{#snippet text()}<svelte:element this={SLOT} />{/snippet}
{#snippet iconSlot()}<svelte:element this={SLOT} name="icon" />{/snippet}

<Badge {variant} {tone} {size} {dot} children={text} icon={hasIcon ? iconSlot : undefined} {@attach connect} />
