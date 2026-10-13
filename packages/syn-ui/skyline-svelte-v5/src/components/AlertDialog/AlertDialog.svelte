<!-- Alert Dialog (AlertDialogRootContract): a small modal confirmation built on Dialog. -->
<script lang="ts">
  import { untrack } from 'svelte'
  import Button from '../Button/Button.svelte'
  import Dialog from '../Dialog/Dialog.svelte'
  import type { AlertDialogProps } from './types'

  let {
    open = $bindable(),
    defaultOpen = false,
    onOpenChange,
    'aria-label': ariaLabel,
    title,
    description,
    confirmLabel = 'Confirm',
    cancelLabel = 'Cancel',
    tone = 'danger',
    onConfirm,
    onCancel,
    trigger,
    children,
  }: AlertDialogProps = $props()

  let internal = $state(untrack(() => defaultOpen))
  const isOpen = $derived(open ?? internal)
  let busy = $state(false)
  let error = $state<string | null>(null)
  let cancelButton: HTMLElement | null = null

  function set(next: boolean) {
    if (next === isOpen) return
    internal = next
    if (open !== undefined) open = next
    if (!next) {
      busy = false
      error = null
    }
    onOpenChange?.(next)
  }

  function cancel() {
    if (busy) return
    onCancel?.()
    set(false)
  }

  async function confirm() {
    if (busy) return
    error = null
    try {
      const result = onConfirm?.()
      if (result instanceof Promise) {
        busy = true
        await result
      }
      busy = false
      set(false)
    } catch (e) {
      busy = false
      error = e instanceof Error ? e.message : String(e)
    }
  }
</script>

<Dialog
  open={isOpen}
  onOpenChange={(v) => (v ? set(true) : cancel())}
  role="alertdialog"
  size="sm"
  {title}
  {description}
  aria-label={ariaLabel}
  closeOnBackdrop={false}
  showClose={false}
  initialFocus={() => cancelButton}
  {trigger}
>
  {#if children}<div class="sky-alert-dialog__content">{@render children()}</div>{/if}
  {#if error}<p class="sky-alert-dialog__error" role="alert">{error}</p>{/if}
  <div class="sky-alert-dialog__footer">
    <span class="sky-alert-dialog__slot" {@attach (node: HTMLElement) => { cancelButton = node.querySelector('button') }}>
      <Button onclick={cancel} disabled={busy}>{cancelLabel}</Button>
    </span>
    <Button variant={tone === 'danger' ? 'outline' : 'solid'} tone={tone} loading={busy} onclick={confirm}>{confirmLabel}</Button>
  </div>
</Dialog>

<style>
  .sky-alert-dialog__content {
    margin: 0 0 var(--ds-space-4);
    font-size: 0.84375rem;
    line-height: var(--ds-line-height-normal);
    color: var(--sky-color-text-code);
  }
  .sky-alert-dialog__error {
    margin: 0 0 var(--ds-space-3);
    font-size: var(--sky-text-data);
    color: var(--sky-color-danger-soft-fg);
  }
  .sky-alert-dialog__footer {
    display: flex;
    flex-wrap: wrap-reverse;
    justify-content: flex-end;
    gap: var(--ds-space-2);
  }
  .sky-alert-dialog__slot {
    display: contents;
  }
</style>
