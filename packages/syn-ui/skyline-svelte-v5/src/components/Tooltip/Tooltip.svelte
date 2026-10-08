<!-- Tooltip (TooltipRootContract). One raised surface, positioned against its trigger. -->
<script lang="ts">
  import { untrack } from 'svelte'
  import { hideFromTopLayer, popoverAttr, positionFloating, pushLayer, showInTopLayer } from '../_internal/layers'
  import { refAttachment, type TriggerProps } from '../_internal/trigger'
  import type { TooltipProps } from './types'

  let {
    open = $bindable(),
    defaultOpen = false,
    onOpenChange,
    delayDuration = 400,
    side = 'top',
    align = 'center',
    content,
    hint,
    mono = true,
    trigger,
    children,
  }: TooltipProps = $props()

  const uid = $props.id()
  const tipId = `${uid}-tooltip`
  let internal = $state(untrack(() => defaultOpen))
  const isOpen = $derived(open ?? internal)
  let anchor: HTMLElement | null = $state(null)
  let surface: HTMLElement | undefined = $state()
  let timer: ReturnType<typeof setTimeout> | undefined

  function set(next: boolean) {
    clearTimeout(timer)
    if (next === isOpen) return
    internal = next
    if (open !== undefined) open = next
    onOpenChange?.(next)
  }
  function openLater() {
    clearTimeout(timer)
    timer = setTimeout(() => set(true), delayDuration)
  }

  $effect(() => {
    if (!isOpen || !anchor || !surface) return
    showInTopLayer(surface)
    const stopPosition = positionFloating(anchor, surface, { side, align, offset: 6 })
    const popLayer = pushLayer({ contains: () => false, onEscape: () => set(false), onOutside: () => set(false) })
    const el = surface
    return () => {
      stopPosition()
      popLayer()
      hideFromTopLayer(el)
    }
  })
  $effect(() => () => clearTimeout(timer))

  const ref = refAttachment((node) => (anchor = node))
  const triggerProps: TriggerProps = $derived({
    ...ref,
    'aria-describedby': tipId,
    'data-state': isOpen ? 'open' : 'closed',
    onpointerenter: (e: PointerEvent) => {
      if (e.pointerType !== 'touch') openLater()
    },
    onpointerleave: () => set(false),
    onfocus: () => set(true),
    onblur: () => set(false),
  })
</script>

{@render trigger(triggerProps)}
<div
  bind:this={surface}
  class="sky-tooltip"
  id={tipId}
  role="tooltip"
  popover={popoverAttr}
  hidden={!isOpen}
  data-state={isOpen ? 'open' : 'closed'}
>
  {#if children}
    {@render children()}
  {:else}
    {#if content}<span class="sky-tooltip__content" data-mono={mono || undefined}>{content}</span>{/if}
    {#if hint}<span class="sky-tooltip__hint">{hint}</span>{/if}
  {/if}
</div>

<style>
  .sky-tooltip {
    position: fixed;
    inset: auto;
    z-index: var(--sky-z-toast);
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-1);
    box-sizing: border-box;
    max-width: min(20rem, calc(100vw - 2 * var(--ds-space-2)));
    margin: 0;
    padding: var(--ds-space-2-5) var(--ds-space-3);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    border-radius: var(--sky-radius-control);
    background: var(--ds-color-surface-raised);
    box-shadow: var(--sky-shadow-float);
    color: var(--ds-color-fg);
    font-size: var(--sky-text-data);
    line-height: var(--ds-line-height-snug);
    pointer-events: none;
    overflow-wrap: anywhere;
  }
  .sky-tooltip[hidden] {
    display: none;
  }
  .sky-tooltip__content[data-mono] {
    font-family: var(--ds-font-mono);
  }
  .sky-tooltip__hint {
    color: var(--ds-color-text-muted);
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-tooltip[data-state='open'] {
      animation: sky-tooltip-in var(--sky-duration-fast) var(--sky-ease-out);
    }
  }
  @keyframes sky-tooltip-in {
    from {
      opacity: 0;
    }
  }
</style>
