<!--
  <sky-button>: Button as a custom element (options in ./options.ts).
  Default slot is the label, slot="icon" the leading icon, slot="icon-end"
  the trailing icon. `label` sets aria-label (needed for icon-only buttons).
  Clicks are native click events on <sky-button>.
-->
<script lang="ts">
  import Button from '../components/Button/Button.svelte'
  import type { ButtonProps } from '../components/Button/types'
  import { SLOT, hostAttachment, watchSlots } from './host'

  type Props = Pick<ButtonProps, 'variant' | 'tone' | 'size' | 'type' | 'href' | 'disabled' | 'loading' | 'block'> & {
    label?: string
  }
  let { variant, tone, size, type = 'button', href, label, disabled = false, loading = false, block = false }: Props = $props()

  let filled = $state(new Set<string>(['']))
  const connect = hostAttachment((host) => watchSlots(host, (s) => (filled = s)))
</script>

{#snippet labelSlot()}<svelte:element this={SLOT} />{/snippet}
{#snippet iconSlot()}<svelte:element this={SLOT} name="icon" />{/snippet}
{#snippet iconEndSlot()}<svelte:element this={SLOT} name="icon-end" />{/snippet}

<Button
  {variant}
  {tone}
  {size}
  {type}
  {href}
  {disabled}
  {loading}
  {block}
  aria-label={label}
  children={filled.has('') ? labelSlot : undefined}
  icon={filled.has('icon') ? iconSlot : undefined}
  iconEnd={filled.has('icon-end') ? iconEndSlot : undefined}
  {@attach connect}
/>
