<!--
  Command palette: Command inside a bare Dialog (CompNav "command · ⌘K").
  The app owns the shortcut; it opens this on its `sky:command` event.
-->
<script lang="ts">
  import Dialog from '../Dialog/Dialog.svelte'
  import Command from './Command.svelte'
  import type { CommandDialogProps } from './types'

  let { open = $bindable(false), onOpenChange, onSelect, search = $bindable(''), ...rest }: CommandDialogProps = $props()

  function setOpen(next: boolean) {
    open = next
    onOpenChange?.(next)
    if (!next) search = ''
  }
</script>

<Dialog open={open} onOpenChange={setOpen} aria-label={rest['aria-label'] ?? 'Command'} showClose={false} bare size="md">
  <Command
    {...rest}
    bind:search
    escHint
    onSelect={(item) => {
      onSelect?.(item)
      setOpen(false)
    }}
  />
</Dialog>
