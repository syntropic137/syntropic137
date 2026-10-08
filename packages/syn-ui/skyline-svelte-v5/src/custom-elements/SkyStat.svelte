<!--
  <sky-stat>: Stat as a custom element (options in ./options.ts). `value` is
  the preformatted figure; leave it unset for the unknown dash. slot="meta"
  is the line under the figure; default-slot content replaces the figure.
-->
<script lang="ts">
  import Stat from '../components/Stat/Stat.svelte'
  import type { StatProps } from '../components/Stat/types'
  import { SLOT, hostAttachment, watchSlots } from './host'

  let { label = '', value, size }: Partial<Pick<StatProps, 'label' | 'value' | 'size'>> = $props()

  let filled = $state(new Set<string>())
  const connect = hostAttachment((host) => watchSlots(host, (s) => (filled = s)))
</script>

{#snippet figure()}<svelte:element this={SLOT} />{/snippet}
{#snippet metaSlot()}<svelte:element this={SLOT} name="meta" />{/snippet}

<Stat
  {label}
  {value}
  {size}
  children={filled.has('') ? figure : undefined}
  meta={filled.has('meta') ? metaSlot : undefined}
  {@attach connect}
/>
