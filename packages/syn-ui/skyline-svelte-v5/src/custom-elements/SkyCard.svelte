<!-- <sky-card>: Card as a custom element (options in ./options.ts). The default slot is the card body. -->
<script lang="ts">
  import Card from '../components/Card/Card.svelte'
  import type { CardProps } from '../components/Card/types'
  import { SLOT, hostAttachment } from './host'

  type Props = Pick<CardProps, 'variant' | 'padding' | 'href' | 'as' | 'interactive' | 'selected'>
  let { variant, padding, href, as, interactive = false, selected = false }: Props = $props()

  const connect = hostAttachment(undefined, { block: true })
</script>

{#snippet body()}<svelte:element this={SLOT} />{/snippet}

<Card {variant} {padding} {href} {as} {interactive} {selected} children={body} {@attach connect} />
