<!--
  <sky-tool-log>: Tool Log Ticker as a custom element (options in
  ./options.ts). Set `rows` ({ time, tool, target, duration }[]) as a JS
  property or a JSON attribute; `speed` is seconds per row, 0 keeps it
  still. Plays only while on screen and stops after about 20s.
-->
<script lang="ts">
  import type { ToolLogProps } from '@syn137/skyline-core/patterns'
  import ToolLogTicker from '../patterns/ToolLogTicker/ToolLogTicker.svelte'
  import { hostAttachment } from './host'

  let { rows = [], speed, label }: Partial<ToolLogProps> = $props()

  const connect = hostAttachment(undefined, { block: true, motion: true })
</script>

<ToolLogTicker {rows} {speed} {label} {@attach connect} />
