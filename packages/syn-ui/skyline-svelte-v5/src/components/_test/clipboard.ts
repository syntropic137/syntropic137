/**
 * A page that is not a secure context (the dashboard over plain http on a LAN
 * address, #742): no `navigator.clipboard`, only `document.execCommand('copy')`.
 * `copied` records what each copy put on the clipboard, read from the
 * textarea the fallback selects; `block()` makes execCommand refuse.
 */
export interface InsecureClipboard {
  readonly copied: string[]
  block(): void
  restore(): void
}

export function insecureClipboard(): InsecureClipboard {
  const clipboard = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
  const execCommand = Object.getOwnPropertyDescriptor(document, 'execCommand')
  const copied: string[] = []
  let blocked = false
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined })
  Object.defineProperty(document, 'execCommand', {
    configurable: true,
    value: (command: string) => {
      const area = document.body.querySelector<HTMLTextAreaElement>(':scope > textarea[readonly]')
      if (blocked || command !== 'copy' || !area) return false
      copied.push(area.value)
      return true
    },
  })
  return {
    copied,
    block: () => {
      blocked = true
    },
    restore: () => {
      if (clipboard) Object.defineProperty(navigator, 'clipboard', clipboard)
      else delete (navigator as { clipboard?: Clipboard }).clipboard
      if (execCommand) Object.defineProperty(document, 'execCommand', execCommand)
      else delete (document as { execCommand?: Document['execCommand'] }).execCommand
    },
  }
}
