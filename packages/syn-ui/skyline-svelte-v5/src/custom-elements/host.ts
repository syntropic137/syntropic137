/**
 * Shared helpers for the <sky-*> custom-element wrappers (custom-element
 * build only: `pnpm run build:ce`). The wrapped components are not changed.
 *
 * Every wrapper renders into an open shadow root. Theme tokens (--ds-*,
 * --sky-*) are inherited custom properties, so the host page sets the theme
 * once on <html data-theme="..."> with @syn137/skyline-themes/all.css and the
 * elements follow it. The shared base layer (styles.css: visually hidden
 * text, focus ring) does not cross the shadow boundary, so each element
 * adopts it here. Elements that animate (the landing elements) also adopt
 * @syn137/skyline-themes/motion.css: a page's own stylesheet never reaches
 * into a shadow root, and every keyframe there stays inside the
 * prefers-reduced-motion guard, so the static end state is the default.
 *
 * Wrappers reach their host element through an attachment on the wrapped
 * component rather than `$host()`, because svelte-check runs without the
 * customElement compile option and does not know `$host` (see options.ts).
 */
import type { Attachment } from 'svelte/attachments'
import motionCss from '@syn137/skyline-themes/motion.css?inline'
import baseCss from '../styles.css?inline'

const sheets = new Map<string, CSSStyleSheet>()

function sheetFor(css: string): CSSStyleSheet | null {
  if (typeof CSSStyleSheet === 'undefined' || !('replaceSync' in CSSStyleSheet.prototype)) return null
  let s = sheets.get(css)
  if (!s) {
    s = new CSSStyleSheet()
    s.replaceSync(css)
    sheets.set(css, s)
  }
  return s
}

function adopt(root: ShadowRoot, css: string): void {
  const s = sheetFor(css)
  if (!s || root.adoptedStyleSheets.includes(s)) return
  root.adoptedStyleSheets = [...root.adoptedStyleSheets, s]
}

/**
 * Wrappers render native <slot> elements with <svelte:element this={SLOT}>:
 * a real slot in the shadow root, without Svelte's deprecated <slot> syntax.
 */
export const SLOT = 'slot'

/** Custom elements are inline by default; block-level wrappers opt in. */
const HOST_BLOCK = ':host { display: block; }'

/**
 * Attachment for the wrapped component's root element: finds the custom
 * element that hosts it, adopts the base layer and hands the host to
 * `onhost`. `block` makes the host display: block; `motion` adopts the
 * motion.css classes. Does nothing outside a shadow root (e.g. in a Svelte app).
 */
export function hostAttachment(
  onhost?: (host: HTMLElement) => void | (() => void),
  opts: { block?: boolean; motion?: boolean } = {},
): Attachment<Element> {
  return (el) => {
    const root = el.getRootNode()
    if (!(root instanceof ShadowRoot) || !(root.host instanceof HTMLElement)) return
    adopt(root, baseCss)
    if (opts.block) adopt(root, HOST_BLOCK)
    if (opts.motion) adopt(root, motionCss)
    return onhost?.(root.host)
  }
}

/** The slots with light-DOM content; '' is the default slot. */
export function filledSlots(host: HTMLElement): Set<string> {
  const out = new Set<string>()
  for (const node of Array.from(host.childNodes)) {
    if (node instanceof Element) out.add(node.getAttribute('slot') ?? '')
    else if (node.nodeType === Node.TEXT_NODE && node.textContent?.trim()) out.add('')
  }
  return out
}

/** Calls `onchange` now and whenever the host's light-DOM children change. */
export function watchSlots(host: HTMLElement, onchange: (filled: Set<string>) => void): () => void {
  onchange(filledSlots(host))
  const mo = new MutationObserver(() => onchange(filledSlots(host)))
  mo.observe(host, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['slot'] })
  return () => mo.disconnect()
}

/** Dispatches a bubbling, composed CustomEvent from the host element. */
export function emit<T>(host: HTMLElement | null, type: string, detail: T): void {
  host?.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }))
}
