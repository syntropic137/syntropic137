<!--
  <sky-eval-explorer>: Eval Explorer as a custom element (options in
  ./options.ts). Set `verifiers` (ExplorerVerifier[]) and `ticks` as JS
  properties or JSON attributes. Dispatches a bubbling, composed
  `verifierchange` event (detail: { index, name }) when the reader picks a
  verifier; `selected` reflects the pick to the attribute.
-->
<script lang="ts">
  import type { EvalExplorerProps } from '@syn137/skyline-core/patterns'
  import EvalExplorer from '../patterns/EvalExplorer/EvalExplorer.svelte'
  import { emit, hostAttachment } from './host'

  let { verifiers = [], passAt, judge, selected = $bindable(), span, ticks, costMax }: Partial<EvalExplorerProps> = $props()

  let host: HTMLElement | null = null
  const connect = hostAttachment(
    (h) => {
      host = h
    },
    { block: true },
  )
  const onselect = (index: number) => emit(host, 'verifierchange', { index, name: verifiers[index]?.name ?? '' })
</script>

<EvalExplorer {verifiers} {passAt} {judge} bind:selected {span} {ticks} {costMax} {onselect} {@attach connect} />
