<!--
  <sky-tag>: Tag as a custom element (options in ./options.ts). Default slot
  is the text, slot="icon" the leading icon. With `removable`, the chip is a
  button and activating it dispatches a bubbling, composed `remove` event
  from <sky-tag>.
-->
<script lang="ts">
  import Tag from '../components/Tag/Tag.svelte'
  import type { TagProps } from '../components/Tag/types'
  import { SLOT, emit, hostAttachment, watchSlots } from './host'

  type Props = Pick<TagProps, 'variant' | 'agent' | 'href' | 'removeLabel'> & { removable?: boolean }
  let { variant, agent, href, removable = false, removeLabel }: Props = $props()

  let host: HTMLElement | null = null
  let hasIcon = $state(false)
  const connect = hostAttachment((h) => {
    host = h
    return watchSlots(h, (s) => (hasIcon = s.has('icon')))
  })
  const onremove = () => emit(host, 'remove', null)
</script>

{#snippet text()}<svelte:element this={SLOT} />{/snippet}
{#snippet iconSlot()}<svelte:element this={SLOT} name="icon" />{/snippet}

<Tag
  {variant}
  {agent}
  {href}
  {removeLabel}
  onremove={removable ? onremove : undefined}
  children={text}
  icon={hasIcon ? iconSlot : undefined}
  {@attach connect}
/>
