<!--
  <sky-iso-city>: the run city as a custom element (options in
  ./options.ts). Set `days` (SkylineDay[]) and the index arrays as JS
  properties or JSON attributes. Content with slot="overlay" (the hero's
  <sky-s-mark>) is drawn over the city, top centre, inside the drifting
  stage; any other light-DOM child is a pre-upgrade fallback.
-->
<script lang="ts">
  import type { HeroCityProps } from '@syn137/skyline-core/patterns'
  import HeroCity from '../patterns/HeroCity/HeroCity.svelte'
  import { SLOT, hostAttachment, watchSlots } from './host'

  let {
    days = [],
    live = [],
    failed = [],
    errored = [],
    animate = false,
    drift = false,
    fill,
    cols,
    rows,
    cell,
    maxSessions,
    label,
  }: Partial<HeroCityProps> = $props()

  let filled = $state(new Set<string>())
  const connect = hostAttachment((host) => watchSlots(host, (s) => (filled = s)), { block: true, motion: true })
</script>

{#snippet overlaySlot()}<svelte:element this={SLOT} name="overlay" />{/snippet}

<HeroCity
  {days}
  {live}
  {failed}
  {errored}
  {animate}
  {drift}
  {fill}
  {cols}
  {rows}
  {cell}
  {maxSessions}
  {label}
  overlay={filled.has('overlay') ? overlaySlot : undefined}
  {@attach connect}
/>
