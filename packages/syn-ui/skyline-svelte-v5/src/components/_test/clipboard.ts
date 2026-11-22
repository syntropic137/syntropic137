/**
 * A page that is not a secure context (the dashboard over plain http on a LAN
 * address, #742): no `navigator.clipboard`, only `document.execCommand('copy')`.
 * `copied` records what each copy put on the clipboard: the text selected in
 * the fallback's textarea, and nothing when that textarea is inert under a
 * modal dialog. `block()` makes execCommand refuse.
 *
 * jsdom has no top layer and matches nothing for `:modal`, so this double
 * models both while it is installed: `showModal()` marks the dialog with the
 * order it was opened in, `:modal` in a document query matches marked
 * dialogs, and the last one opened is the top modal (#2263).
 */
export interface InsecureClipboard {
  readonly copied: string[]
  block(): void
  restore(): void
}

const MODAL = 'data-test-modal'

export function insecureClipboard(): InsecureClipboard {
  const copied: string[] = []
  let blocked = false
  const restorers = [
    replace(navigator, 'clipboard', undefined),
    replace(document, 'execCommand', (command: string) => {
      const area = document.querySelector<HTMLTextAreaElement>('textarea[readonly]')
      if (blocked || command !== 'copy' || !area) return false
      // Chromium returns true even when nothing is selected or the textarea
      // is inert outside the top modal; it just copies nothing.
      const top = topModal()
      if (!top || top.contains(area)) copied.push(area.value.slice(area.selectionStart, area.selectionEnd))
      return true
    }),
    ...modalDialogs(),
  ]
  return {
    copied,
    block: () => {
      blocked = true
    },
    restore: () => restorers.reverse().forEach((restore) => restore()),
  }
}

/** The open modal opened last: the only part of the page that is not inert. */
function topModal(): HTMLDialogElement | undefined {
  const modals = [...document.querySelectorAll<HTMLDialogElement>(`dialog[open][${MODAL}]`)]
  return modals.sort((a, b) => Number(a.getAttribute(MODAL)) - Number(b.getAttribute(MODAL))).at(-1)
}

/** `showModal`/`close` that mark modality, and `:modal` document queries that read the mark. */
function modalDialogs(): Array<() => void> {
  let opened = 0
  const dialog = HTMLDialogElement.prototype
  const { showModal, close } = dialog
  const query = Document.prototype.querySelectorAll
  return [
    replace(dialog, 'showModal', function (this: HTMLDialogElement) {
      if (showModal) showModal.call(this)
      else this.setAttribute('open', '')
      this.setAttribute(MODAL, String(++opened))
    }),
    replace(dialog, 'close', function (this: HTMLDialogElement, returnValue?: string) {
      this.removeAttribute(MODAL)
      if (close) close.call(this, returnValue)
      else this.removeAttribute('open')
    }),
    replace(Document.prototype, 'querySelectorAll', function (this: Document, selectors: string) {
      return query.call(this, selectors.replaceAll(':modal', `[open][${MODAL}]`))
    }),
  ]
}

/** Override `key` on `target` and return what puts the original back. */
function replace<T extends object>(target: T, key: PropertyKey, value: unknown): () => void {
  const original = Object.getOwnPropertyDescriptor(target, key)
  Object.defineProperty(target, key, { configurable: true, writable: true, value })
  return () => {
    if (original) Object.defineProperty(target, key, original)
    else Reflect.deleteProperty(target, key)
  }
}
