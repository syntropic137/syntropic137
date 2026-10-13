<!--
  The small line glyphs the component sheets draw (CompActions, CompDisplay,
  CompNav), on the canvas's 16-unit grid. Components use these instead of an
  icon library so the base layer carries no runtime dependency. Screens use
  @lucide/svelte for everything else.
-->
<script lang="ts" module>
  export type GlyphName =
    | 'copy'
    | 'check'
    | 'cross'
    | 'dash'
    | 'clock'
    | 'chevron-right'
    | 'chevron-left'
    | 'chevron-down'
    | 'chevron-up'
    | 'search'
    | 'warning'
    | 'info'
    | 'home'
    | 'diamond'
    | 'more'

  const PATHS: Record<GlyphName, string> = {
    copy: 'M5.5 5.5h8v8h-8zM10.5 5.5V2.5h-8v8h3',
    check: 'M3.5 8.5l3 3 6-7',
    cross: 'M4.5 4.5l7 7M11.5 4.5l-7 7',
    dash: 'M4 8h8',
    clock: 'M8 4.5V8l2.5 1.5',
    'chevron-right': 'M6 3.5L10.5 8 6 12.5',
    'chevron-left': 'M10 3.5L5.5 8l4.5 4.5',
    'chevron-down': 'M3.5 6L8 10.5 12.5 6',
    'chevron-up': 'M3.5 10L8 5.5l4.5 4.5',
    search: 'M10.25 10.25L13.5 13.5',
    warning: 'M8 2.25l6 10.75H2zM8 6.5v3M8 11.4v.1',
    info: 'M8 7.25v4M8 4.6v.1',
    home: 'M2.75 7.25L8 2.75l5.25 4.5V13a.5.5 0 0 1-.5.5H9.5V9.75h-3v3.75H3.25a.5.5 0 0 1-.5-.5z',
    diamond: 'M8 1.75L14.25 8 8 14.25 1.75 8z',
    more: 'M3.5 8h.1M8 8h.1M12.5 8h.1',
  }
</script>

<script lang="ts">
  let {
    name,
    size = 15,
    strokeWidth = 1.5,
    class: className = '',
  }: { name: GlyphName; size?: number; strokeWidth?: number; class?: string } = $props()
</script>

<svg
  class={['sky-glyph', className]}
  width={size}
  height={size}
  viewBox="0 0 16 16"
  fill="none"
  stroke="currentColor"
  stroke-width={name === 'more' ? strokeWidth + 1 : strokeWidth}
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
  focusable="false"
>
  {#if name === 'search'}<circle cx="7" cy="7" r="4.25" />{/if}
  {#if name === 'info'}<circle cx="8" cy="8" r="6" />{/if}
  <path d={PATHS[name]} />
</svg>

<style>
  .sky-glyph {
    flex-shrink: 0;
    display: block;
  }
</style>
