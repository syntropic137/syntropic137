<!-- Popover (PopoverRootContract): the shared raised surface, anchored and light-dismissed. -->
<script lang="ts">
  import { tick, untrack } from 'svelte'
  import { focusables, hideFromTopLayer, popoverAttr, positionFloating, pushLayer, showInTopLayer } from '../_internal/layers'
  import { refAttachment, type TriggerProps } from '../_internal/trigger'
  import type { PopoverProps } from './types'

  let {
    open = $bindable(),
    defaultOpen = false,
    onOpenChange,
    side = 'bottom',
    align = 'start',
    label,
    heading,
    width = '15rem',
    trigger,
    children,
  }: PopoverProps = $props()

  const uid = $props.id()
  const panelId = `${uid}-popover`
  let internal = $state(untrack(() => defaultOpen))
  const isOpen = $derived(open ?? internal)
  let anchor: HTMLElement | null = $state(null)
  let surface: HTMLElement | undefined = $state()

  function set(next: boolean, opts: { returnFocus?: boolean } = {}) {
    if (next === isOpen) return
    internal = next
    if (open !== undefined) open = next
    onOpenChange?.(next)
    if (!next && opts.returnFocus) anchor?.focus()
  }
  const close = () => set(false, { returnFocus: true })

  $effect(() => {
    if (!isOpen || !anchor || !surface) return
    const el = surface
    const a = anchor
    showInTopLayer(el)
    const stopPosition = positionFloating(a, el, { side, align })
    const popLayer = pushLayer({
      contains: (t) => el.contains(t) || a.contains(t),
      onEscape: () => set(false, { returnFocus: true }),
      onOutside: () => set(false),
    })
    void tick().then(() => (focusables(el)[0] ?? el).focus({ preventScroll: true }))
    return () => {
      stopPosition()
      popLayer()
      hideFromTopLayer(el)
    }
  })

  function onFocusOut(e: FocusEvent) {
    const to = e.relatedTarget as Node | null
    if (to && !surface?.contains(to) && !anchor?.contains(to)) set(false)
  }

  const ref = refAttachment((node) => (anchor = node))
  const triggerProps: TriggerProps = $derived({
    ...ref,
    'aria-haspopup': 'dialog',
    'aria-expanded': isOpen,
    'aria-controls': panelId,
    'data-state': isOpen ? 'open' : 'closed',
    onclick: () => set(!isOpen),
  })
</script>

{@render trigger(triggerProps)}
{#if isOpen}
  <div
    bind:this={surface}
    class="sky-popover"
    id={panelId}
    role="dialog"
    aria-label={label}
    tabindex="-1"
    popover={popoverAttr}
    data-state="open"
    style:width
    onfocusout={onFocusOut}
  >
    {#if heading}<span class="sky-popover__heading" aria-hidden="true">{heading}</span>{/if}
    {@render children?.({ close })}
  </div>
{/if}

<style>
  .sky-popover {
    position: fixed;
    inset: auto;
    z-index: var(--sky-z-overlay);
    display: flex;
    flex-direction: column;
    gap: var(--ds-space-0-5);
    box-sizing: border-box;
    max-width: calc(100vw - 2 * var(--ds-space-2));
    max-height: max(12rem, var(--sky-available));
    margin: 0;
    padding: var(--ds-space-2);
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    border-radius: var(--sky-radius-xl);
    background: var(--ds-color-surface-raised);
    box-shadow: var(--sky-shadow-overlay);
    color: var(--ds-color-fg);
    font-size: var(--ds-text-md);
    overflow: auto;
    overscroll-behavior: contain;
  }
  .sky-popover:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-popover__heading {
    padding: var(--ds-space-1-5) var(--ds-space-2-5);
    font-family: var(--ds-font-mono);
    font-size: var(--sky-text-label);
    letter-spacing: var(--sky-tracking-label);
    text-transform: uppercase;
    color: var(--ds-color-text-subtle);
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-popover {
      animation: sky-popover-in var(--sky-duration-base) var(--sky-ease-out);
    }
  }
  @keyframes sky-popover-in {
    from {
      opacity: 0;
      transform: translateY(-4px);
    }
  }
</style>
