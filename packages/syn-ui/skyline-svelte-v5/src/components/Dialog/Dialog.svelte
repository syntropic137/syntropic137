<!-- Dialog (DialogRootContract) on the native modal <dialog>. -->
<script lang="ts">
  import { tick, untrack } from 'svelte'
  import Glyph from '../_internal/Glyph.svelte'
  import { focusables, lockScroll } from '../_internal/layers'
  import { refAttachment, type TriggerProps } from '../_internal/trigger'
  import type { DialogProps } from './types'

  let {
    open = $bindable(),
    defaultOpen = false,
    onOpenChange,
    modal = true,
    'aria-label': ariaLabel,
    title,
    titleId,
    description,
    size = 'md',
    actions,
    footer,
    trigger,
    children,
    closeOnBackdrop = true,
    showClose = true,
    role = 'dialog',
    initialFocus,
    bare = false,
  }: DialogProps = $props()

  const uid = $props.id()
  const dialogId = `${uid}-dialog`
  const titleElId = `${uid}-title`
  const descId = `${uid}-description`
  let internal = $state(untrack(() => defaultOpen))
  const isOpen = $derived(open ?? internal)
  let dialog: HTMLDialogElement | undefined = $state()
  let anchor: HTMLElement | null = $state(null)
  /** Focus to restore on close. */
  let returnTo: HTMLElement | null = null

  function set(next: boolean) {
    if (next === isOpen) return
    internal = next
    if (open !== undefined) open = next
    onOpenChange?.(next)
  }
  const close = () => set(false)

  $effect(() => {
    const el = dialog
    if (!el || !isOpen) return
    const isModal = untrack(() => modal)
    returnTo = (document.activeElement as HTMLElement | null) ?? untrack(() => anchor)
    if (!el.open) {
      if (isModal) el.showModal()
      else el.show()
    }
    const unlock = isModal ? lockScroll() : () => {}
    void tick().then(() => {
      const target = initialFocus?.() ?? focusables(el).find((n) => !('skyDialogClose' in n.dataset)) ?? el
      target.focus()
    })
    return () => {
      unlock()
      if (el.open) el.close()
      const back = returnTo?.isConnected ? returnTo : anchor
      back?.focus?.()
    }
  })

  function onCancel(e: Event) {
    // Escape: keep the open state in sync instead of letting the element close itself.
    e.preventDefault()
    close()
  }

  function onClick(e: MouseEvent) {
    // A click on the <dialog> itself (not its panel) is a click on the backdrop.
    if (closeOnBackdrop && e.target === dialog) close()
  }

  const ref = refAttachment((node) => (anchor = node))
  const triggerProps: TriggerProps = $derived({
    ...ref,
    'aria-haspopup': 'dialog',
    'aria-expanded': isOpen,
    'aria-controls': dialogId,
    'data-state': isOpen ? 'open' : 'closed',
    onclick: () => set(true),
  })
</script>

{#if trigger}{@render trigger(triggerProps)}{/if}

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions: the backdrop click is a pointer convenience; Escape is the keyboard path. -->
<dialog
  bind:this={dialog}
  class="sky-dialog"
  id={dialogId}
  {role}
  aria-modal={modal || undefined}
  aria-label={title ? undefined : ariaLabel}
  aria-labelledby={title ? titleElId : undefined}
  aria-describedby={description ? descId : undefined}
  data-size={size}
  data-state={isOpen ? 'open' : 'closed'}
  oncancel={onCancel}
  onclick={onClick}
>
  {#if isOpen}
    <div class="sky-dialog__panel" data-bare={bare || undefined}>
      {#if title || actions || showClose}
        <header class="sky-dialog__header" data-plain={!title || undefined}>
          {#if title}
            <h2 class="sky-dialog__title" id={titleElId}>
              {title}{#if titleId}&nbsp;<span class="sky-dialog__title-id">{titleId}</span>{/if}
            </h2>
          {/if}
          <div class="sky-dialog__actions">
            {@render actions?.()}
            {#if showClose}
              <button type="button" class="sky-dialog__close" aria-label="Close" data-sky-dialog-close="" onclick={close}>
                <Glyph name="cross" size={14} strokeWidth={1.9} />
              </button>
            {/if}
          </div>
        </header>
      {/if}
      {#if description}<p class="sky-dialog__description" id={descId}>{description}</p>{/if}
      <div class="sky-dialog__body">{@render children?.({ close })}</div>
      {#if footer}<footer class="sky-dialog__footer">{@render footer()}</footer>{/if}
    </div>
  {/if}
</dialog>

<style>
  .sky-dialog {
    /* Phone: a sheet from the bottom edge. */
    box-sizing: border-box;
    width: calc(100% - 2 * var(--ds-space-2));
    max-width: none;
    max-height: calc(100dvh - var(--ds-space-10));
    margin: auto auto var(--ds-space-2);
    padding: 0;
    border: var(--ds-border-width) solid var(--sky-color-border-strong);
    border-radius: var(--sky-radius-xl);
    background: var(--ds-color-surface-raised);
    box-shadow: var(--sky-shadow-overlay);
    color: var(--ds-color-fg);
    overflow: hidden;
    overscroll-behavior: contain;
  }
  .sky-dialog[open] {
    display: flex;
  }
  .sky-dialog::backdrop {
    background: var(--sky-color-scrim);
  }
  .sky-dialog:focus-visible {
    outline: none;
  }
  .sky-dialog__panel {
    display: flex;
    flex-direction: column;
    width: 100%;
    min-height: 0;
  }
  .sky-dialog__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--ds-space-3);
    flex-shrink: 0;
    padding: var(--ds-space-3-5) var(--ds-space-3-5) var(--ds-space-3-5) var(--ds-space-5);
    border-bottom: var(--ds-border-width) solid var(--sky-color-border-muted);
  }
  .sky-dialog__header[data-plain] {
    justify-content: flex-end;
    border-bottom: 0;
    padding-bottom: 0;
  }
  .sky-dialog__title {
    min-width: 0;
    margin: 0;
    font-size: var(--sky-text-body);
    font-weight: var(--ds-font-weight-semibold);
    overflow-wrap: anywhere;
  }
  .sky-dialog__title-id {
    font-family: var(--ds-font-mono);
    font-size: 0.75rem;
    font-weight: var(--ds-font-weight-regular);
    color: var(--ds-color-text-muted);
  }
  .sky-dialog__actions {
    display: flex;
    align-items: center;
    gap: var(--ds-space-1-5);
    flex-shrink: 0;
  }
  .sky-dialog__close {
    display: flex;
    align-items: center;
    justify-content: center;
    width: var(--sky-size-control-sm);
    height: var(--sky-size-control-sm);
    padding: 0;
    border: 0;
    border-radius: var(--ds-radius-sm);
    background: transparent;
    color: var(--ds-color-text-muted);
    cursor: pointer;
  }
  .sky-dialog__close:hover {
    background: var(--sky-color-control-hover);
    color: var(--ds-color-fg);
  }
  .sky-dialog__close:focus-visible {
    outline: var(--sky-focus-ring-width) solid var(--sky-color-focus);
    outline-offset: var(--sky-focus-ring-offset);
  }
  .sky-dialog__description {
    margin: 0;
    padding: var(--ds-space-4) var(--ds-space-5) 0;
    font-size: 0.84375rem;
    line-height: var(--ds-line-height-normal);
    color: var(--sky-color-text-code);
  }
  .sky-dialog__body {
    flex: 1 1 auto;
    min-height: 0;
    padding: var(--ds-space-4) var(--ds-space-5);
    overflow: auto;
  }
  .sky-dialog__panel[data-bare] .sky-dialog__body {
    padding: 0;
  }
  .sky-dialog__footer {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: var(--ds-space-2);
    flex-shrink: 0;
    padding: 0 var(--ds-space-5) var(--ds-space-5);
  }

  @media (min-width: 48rem) {
    .sky-dialog {
      width: min(32.5rem, calc(100% - 2 * var(--sky-gutter)));
      max-height: calc(100dvh - 2 * var(--ds-space-12));
      margin: auto;
    }
    .sky-dialog[data-size='sm'] {
      width: min(23.75rem, calc(100% - 2 * var(--sky-gutter)));
    }
    .sky-dialog[data-size='lg'] {
      width: min(48rem, calc(100% - 2 * var(--sky-gutter)));
    }
    .sky-dialog[data-size='full'] {
      width: calc(100% - 2 * var(--sky-gutter));
      height: calc(100dvh - 2 * var(--ds-space-12));
    }
  }
  @media (pointer: coarse) {
    .sky-dialog__close {
      width: var(--sky-size-touch);
      height: var(--sky-size-touch);
    }
  }
  @media (prefers-reduced-motion: no-preference) {
    .sky-dialog[open] {
      animation: sky-dialog-in var(--sky-duration-base) var(--sky-ease-out);
    }
    .sky-dialog[open]::backdrop {
      animation: sky-backdrop-in var(--sky-duration-base) var(--sky-ease-out);
    }
  }
  @keyframes sky-dialog-in {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
  }
  @keyframes sky-backdrop-in {
    from {
      opacity: 0;
    }
  }
</style>
