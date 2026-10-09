<!--
  Drag a rectangle to screenshot one area (React widget's "Capture area").
  Esc cancels. Keyboard users take the full-viewport screenshot instead.
-->
<script lang="ts">
  import { onMount } from 'svelte'
  import type { Area } from './capture'
  import { FEEDBACK_UI_ATTR } from './element'

  let { onselect, oncancel }: { onselect: (a: Area) => void; oncancel: () => void } = $props()

  let start = $state<{ x: number; y: number } | null>(null)
  let end = $state<{ x: number; y: number } | null>(null)
  let layer: HTMLDivElement | undefined = $state()
  onMount(() => layer?.focus())

  const area = $derived<Area | null>(
    start && end
      ? { x: Math.min(start.x, end.x), y: Math.min(start.y, end.y), width: Math.abs(end.x - start.x), height: Math.abs(end.y - start.y) }
      : null,
  )

  function down(e: PointerEvent) {
    layer?.setPointerCapture(e.pointerId)
    start = { x: e.clientX, y: e.clientY }
    end = start
  }
  function moveTo(e: PointerEvent) {
    if (start) end = { x: e.clientX, y: e.clientY }
  }
  function up() {
    const a = area
    start = null
    end = null
    if (a && a.width > 8 && a.height > 8) onselect(a)
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div
  bind:this={layer}
  class="sky-fb-area"
  role="dialog"
  aria-modal="true"
  aria-label="Drag to select an area"
  tabindex="0"
  {...{ [FEEDBACK_UI_ATTR]: '' }}
  onpointerdown={down}
  onpointermove={moveTo}
  onpointerup={up}
  onkeydown={(e) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      oncancel()
    }
  }}
>
  {#if area}
    <div class="sky-fb-area__box" style:left="{area.x}px" style:top="{area.y}px" style:width="{area.width}px" style:height="{area.height}px"></div>
  {:else}
    <div class="sky-fb-area__scrim"></div>
  {/if}
  <div class="sky-fb-area__hint">Drag to select an area · <kbd>Esc</kbd> to cancel</div>
</div>

<style>
  .sky-fb-area {
    position: fixed;
    inset: 0;
    z-index: var(--sky-z-toast);
    cursor: crosshair;
    outline: none;
    touch-action: none;
  }
  .sky-fb-area__scrim {
    position: absolute;
    inset: 0;
    background: var(--sky-feedback-scrim);
  }
  .sky-fb-area__box {
    position: absolute;
    outline: var(--sky-focus-ring-width) dashed var(--sky-feedback-pick);
    box-shadow: 0 0 0 100vmax var(--sky-feedback-scrim);
  }
  .sky-fb-area__hint {
    position: fixed;
    left: 50%;
    top: var(--ds-space-4);
    transform: translateX(-50%);
    padding: var(--ds-space-2) var(--ds-space-3);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-surface-raised);
    color: var(--ds-color-fg);
    font-size: var(--ds-text-sm);
    pointer-events: none;
  }
</style>
