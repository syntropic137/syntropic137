/**
 * Shared setup for component tests. Each test file starts with
 *
 *   // @vitest-environment jsdom
 *   import '../_test/setup'
 *
 * so the package's Node default stays fast for pure tests.
 */
import { cleanup } from '@testing-library/svelte'
import { createRawSnippet, type Snippet } from 'svelte'
import { afterEach } from 'vitest'

afterEach(() => cleanup())

// jsdom gaps the overlay components touch.
const proto = globalThis.HTMLDialogElement?.prototype as (HTMLDialogElement & { __skyPolyfill?: boolean }) | undefined
if (proto && typeof proto.showModal !== 'function') {
  proto.showModal = function (this: HTMLDialogElement) {
    this.setAttribute('open', '')
  }
  proto.show = proto.showModal
  proto.close = function (this: HTMLDialogElement) {
    if (!this.hasAttribute('open')) return
    this.removeAttribute('open')
    this.dispatchEvent(new Event('close'))
  }
}
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {}
}

/** A text snippet for `children` and friends. */
export function text(value: string): Snippet {
  return createRawSnippet(() => ({ render: () => `<span>${escapeHtml(value)}</span>` }))
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!)
}
