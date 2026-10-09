<!--
  Element picker (React widget's "Pin to element"): the page dims, the
  element under the pointer is outlined, a click or tap pins it. Keyboard:
  Tab / arrows move between candidates, Enter pins, Esc cancels. A
  transparent layer takes every pointer event, so a pick never also follows
  the link or presses the button underneath.
-->
<script lang="ts">
  import { onMount } from 'svelte'
  import { FEEDBACK_UI_ATTR, candidateAt, keyboardCandidates, pin, type PinnedElement } from './element'

  let { onpick, oncancel }: { onpick: (p: PinnedElement) => void; oncancel: () => void } = $props()

  let target = $state<Element | null>(null)
  let rect = $state<DOMRect | null>(null)
  let layer: HTMLDivElement | undefined = $state()
  let list: Element[] = []
  let index = -1

  const label = $derived(target ? pin(target).label : '')

  function show(el: Element | null) {
    target = el
    rect = el?.getBoundingClientRect() ?? null
  }

  onMount(() => {
    list = keyboardCandidates()
    layer?.focus()
    const onScroll = () => show(target)
    addEventListener('scroll', onScroll, true)
    return () => removeEventListener('scroll', onScroll, true)
  })

  function onMove(e: PointerEvent) {
    show(candidateAt(e.clientX, e.clientY))
  }

  function onClick(e: MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    const el = candidateAt(e.clientX, e.clientY)
    if (el) onpick(pin(el, e.clientX, e.clientY))
  }

  function move(step: number) {
    if (list.length === 0) return
    index = (index + step + list.length) % list.length
    const el = list[index]!
    el.scrollIntoView({ block: 'nearest' })
    show(el)
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') oncancel()
    else if (e.key === 'Tab') move(e.shiftKey ? -1 : 1)
    else if (e.key === 'ArrowDown' || e.key === 'ArrowRight') move(1)
    else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') move(-1)
    else if (e.key === 'Enter' && target) onpick(pin(target))
    else return
    e.preventDefault()
    e.stopPropagation()
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_click_events_have_key_events: the layer owns keyboard picking in onkeydown -->
<div
  bind:this={layer}
  class="sky-fb-pick"
  role="dialog"
  aria-modal="true"
  aria-label="Pick an element"
  tabindex="0"
  data-testid="feedback-picker"
  {...{ [FEEDBACK_UI_ATTR]: '' }}
  onpointermove={onMove}
  onpointerdown={onMove}
  onclick={onClick}
  onkeydown={onKey}
>
  {#if rect}
    <div
      class="sky-fb-pick__box"
      style:left="{rect.left}px"
      style:top="{rect.top}px"
      style:width="{rect.width}px"
      style:height="{rect.height}px"
    ></div>
  {:else}
    <div class="sky-fb-pick__scrim"></div>
  {/if}
  <div class="sky-fb-pick__hint" aria-live="polite">
    {#if label}<code>{label}</code>{:else}Click or tap an element to pin feedback{/if}
    <span>· Tab to cycle, Enter to pin, <kbd>Esc</kbd> to cancel</span>
  </div>
</div>

<style>
  .sky-fb-pick {
    position: fixed;
    inset: 0;
    z-index: var(--sky-z-toast);
    cursor: crosshair;
    outline: none;
  }
  .sky-fb-pick__scrim {
    position: absolute;
    inset: 0;
    background: var(--sky-feedback-scrim);
  }
  .sky-fb-pick__box {
    position: absolute;
    border-radius: var(--ds-radius-sm);
    outline: var(--sky-focus-ring-width) solid var(--sky-feedback-pick);
    background: var(--sky-feedback-pick-fill);
    /* Dims everything outside the outlined element. */
    box-shadow: 0 0 0 100vmax var(--sky-feedback-scrim);
    pointer-events: none;
    transition: all var(--sky-duration-fast) var(--sky-ease-out);
  }
  .sky-fb-pick__hint {
    position: fixed;
    left: 50%;
    top: var(--ds-space-4);
    transform: translateX(-50%);
    max-width: calc(100vw - 2 * var(--sky-gutter));
    padding: var(--ds-space-2) var(--ds-space-3);
    border-radius: var(--ds-radius-full);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    background: var(--ds-color-surface-raised);
    color: var(--ds-color-fg);
    font-size: var(--ds-text-sm);
    pointer-events: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sky-fb-pick__hint span {
    color: var(--ds-color-text-muted);
  }
  .sky-fb-pick__hint code {
    font-family: var(--ds-font-mono);
  }
</style>
