/**
 * Element pinning for the feedback bubble: which element a pointer is over,
 * a stable selector for it, and a short human label. Ports the React
 * widget's useHoverHighlight / getElementPath / describeElement, with the
 * selector preferring data-testid, then aria-label, then a short CSS path.
 */

/** Our own UI (bubble, picker, dialog) carries this attribute and is never a candidate. */
export const FEEDBACK_UI_ATTR = 'data-sky-feedback-ui'

const SKIP_TAGS = new Set(['HTML', 'BODY', 'MAIN', 'ARTICLE', 'SECTION', 'ASIDE', 'HEADER', 'FOOTER', 'NAV'])
const MIN_SIZE = 20
const MAX_VIEWPORT_RATIO = 0.8
const MAX_TEXT = 40
const MAX_DEPTH = 4

export interface PinnedBox {
  x: number
  y: number
  width: number
  height: number
}

export interface PinnedElement {
  /** Stable selector: `[data-testid="..."]`, `tag[aria-label="..."]` or a short CSS path. */
  selector: string
  xpath: string
  tag: string
  /** `button "Cancel run"`, for the chip. */
  label: string
  text: string
  box: PinnedBox
  clickX: number
  clickY: number
}

const isOurs = (el: Element): boolean => el.closest(`[${FEEDBACK_UI_ATTR}]`) !== null

/** Skip landmarks, tiny targets and near-full-viewport wrappers, like the React widget. */
export function isCandidate(el: Element, viewportArea: number): boolean {
  if (isOurs(el) || SKIP_TAGS.has(el.tagName)) return false
  const r = el.getBoundingClientRect()
  if (r.width < MIN_SIZE || r.height < MIN_SIZE) return false
  return r.width * r.height <= viewportArea * MAX_VIEWPORT_RATIO
}

/** The best element under a point: the topmost candidate. */
export function candidateAt(x: number, y: number): Element | null {
  const area = window.innerWidth * window.innerHeight
  for (const el of document.elementsFromPoint(x, y)) if (isCandidate(el, area)) return el
  return null
}

/** Every candidate in reading order, for keyboard picking (Tab / arrows). */
export function keyboardCandidates(root: ParentNode = document): Element[] {
  const area = window.innerWidth * window.innerHeight
  const sel = '[data-testid], [aria-label], a[href], button, input, select, textarea, [role="row"], [data-sky-row], h1, h2, h3, img'
  return [...root.querySelectorAll(sel)].filter((el) => isCandidate(el, area) && el.getClientRects().length > 0)
}

const quote = (v: string): string => `"${v.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`

function unique(selector: string): boolean {
  try {
    return document.querySelectorAll(selector).length === 1
  } catch {
    return false
  }
}

function step(el: Element): string {
  const tag = el.tagName.toLowerCase()
  if (el.id && !/\d{3,}|^[a-z0-9]{8,}-/i.test(el.id)) return `#${CSS.escape(el.id)}`
  const parent = el.parentElement
  if (!parent) return tag
  const same = [...parent.children].filter((c) => c.tagName === el.tagName)
  return same.length > 1 ? `${tag}:nth-of-type(${same.indexOf(el) + 1})` : tag
}

function byTestId(el: Element): string | null {
  const v = el.getAttribute('data-testid')
  return v ? `[data-testid=${quote(v)}]` : null
}

function byAriaLabel(el: Element): string | null {
  const v = el.getAttribute('aria-label')
  return v ? `${el.tagName.toLowerCase()}[aria-label=${quote(v)}]` : null
}

/** Ancestor steps, closest first, stopping at an id, a testid anchor or MAX_DEPTH. */
function pathSteps(el: Element): string[] {
  const steps: string[] = []
  let cur: Element | null = el
  while (cur && cur !== document.body && cur !== document.documentElement && steps.length < MAX_DEPTH) {
    const anchor = cur !== el ? byTestId(cur) : null
    const s = anchor ?? step(cur)
    steps.push(s)
    if (anchor || s.startsWith('#')) break
    cur = cur.parentElement
  }
  return steps
}

/** Shortest unique suffix of the ancestor path (or the whole capped path). */
function byCssPath(el: Element): string {
  const steps = pathSteps(el)
  for (let n = 1; n <= steps.length; n++) {
    const s = steps.slice(0, n).reverse().join(' > ')
    if (unique(s)) return s
  }
  return steps.reverse().join(' > ')
}

const STRATEGIES: readonly ((el: Element) => string | null)[] = [byTestId, byAriaLabel]

/** data-testid > aria-label > short CSS path, first unique one wins. */
export function selectorFor(el: Element): string {
  for (const strategy of STRATEGIES) {
    const s = strategy(el)
    if (s && unique(s)) return s
  }
  return byCssPath(el)
}

/** Absolute XPath, as the React widget records it. */
export function xpathFor(el: Element): string {
  const parts: string[] = []
  let cur: Element | null = el
  while (cur && cur !== document.documentElement) {
    const parent: Element | null = cur.parentElement
    const tag = cur.tagName.toLowerCase()
    const same = parent ? [...parent.children].filter((c) => c.tagName === cur!.tagName) : []
    parts.unshift(same.length > 1 ? `${tag}[${same.indexOf(cur) + 1}]` : tag)
    cur = parent
  }
  return `/html/${parts.join('/')}`
}

function truncate(text: string): string {
  const t = text.replace(/\s+/g, ' ').trim()
  return t.length > MAX_TEXT ? `${t.slice(0, MAX_TEXT - 1)}…` : t
}

function accessibleText(el: Element): string {
  const named = el.getAttribute('aria-label') ?? el.getAttribute('title') ?? el.getAttribute('alt')
  if (named) return named
  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) return el.placeholder || el.name
  return el.textContent ?? ''
}

/** An icon's inner <path>/<svg> says nothing; name the element that owns it. */
function owner(el: Element): Element {
  return el instanceof SVGElement ? (el.closest('svg')?.parentElement ?? el) : el
}

export function pin(target: Element, clickX?: number, clickY?: number): PinnedElement {
  const el = owner(target)
  const r = el.getBoundingClientRect()
  const tag = el.tagName.toLowerCase()
  const text = truncate(accessibleText(el))
  return {
    selector: selectorFor(el),
    xpath: xpathFor(el),
    tag,
    text,
    label: text ? `${tag} "${text}"` : tag,
    box: { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) },
    clickX: Math.round(clickX ?? r.left + r.width / 2),
    clickY: Math.round(clickY ?? r.top + r.height / 2),
  }
}
