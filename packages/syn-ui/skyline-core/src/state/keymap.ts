/**
 * The one app-wide keymap. The shell's keydown handler and the `?`
 * shortcuts overlay both read KEYMAP, so the overlay cannot list a binding
 * the handler does not have (or miss one it does).
 *
 * Pure: the caller turns a KeyboardEvent into a KeyInput (including whether
 * focus is in a text field or a modal is open) and performs the action.
 * Chords (`g` then `e`) time out after CHORD_MS, measured with the caller's
 * clock (`at`), so there are no timers here.
 */

export type KeymapSection = 'overview' | 'executions' | 'sessions' | 'workflows' | 'evals' | 'artifacts' | 'triggers' | 'repos'

export type KeyAction =
  | { type: 'palette' }
  | { type: 'goto'; section: KeymapSection }
  | { type: 'row'; move: 'next' | 'prev' }
  | { type: 'open' }
  | { type: 'back' }
  | { type: 'search' }
  | { type: 'help' }
  | { type: 'feedback'; mode: FeedbackMode }

/** Feedback widget entry points (the React widget's shortcuts, plus `f`). */
export type FeedbackMode = 'note' | 'pick' | 'recent'

export type KeyGroup = 'General' | 'Go to' | 'Lists' | 'Feedback'

/** A feature a binding needs; the overlay hides bindings whose feature is off. */
export type KeyFeature = 'feedback'

export interface KeyBinding {
  id: string
  /** Alternative sequences; each is a list of key tokens pressed in order. `Mod+k` is Cmd or Ctrl + K. */
  keys: readonly (readonly string[])[]
  label: string
  group: KeyGroup
  action: KeyAction
  /** Fires even while typing in a field or with a modal open. */
  global?: boolean
  /** Only live when this feature is on. */
  requires?: KeyFeature
}

/** Second key of the `g` chord for each section. */
export const GOTO_KEYS = {
  overview: 'o',
  executions: 'e',
  sessions: 's',
  workflows: 'w',
  evals: 'v',
  artifacts: 'a',
  triggers: 't',
  repos: 'r',
} as const satisfies Record<KeymapSection, string>

const SECTION_LABEL: Record<KeymapSection, string> = {
  overview: 'Overview',
  executions: 'Executions',
  sessions: 'Sessions',
  workflows: 'Workflows',
  evals: 'Evals',
  artifacts: 'Artifacts',
  triggers: 'Triggers',
  repos: 'Repos',
}

const SECTIONS = Object.keys(GOTO_KEYS) as KeymapSection[]

export const KEYMAP: readonly KeyBinding[] = [
  { id: 'palette', keys: [['Mod+k']], label: 'Open the command palette', group: 'General', action: { type: 'palette' }, global: true },
  { id: 'help', keys: [['?']], label: 'Show keyboard shortcuts', group: 'General', action: { type: 'help' } },
  { id: 'search', keys: [['/']], label: 'Search this list', group: 'General', action: { type: 'search' } },
  { id: 'back', keys: [['Escape'], ['Backspace']], label: 'Go back', group: 'General', action: { type: 'back' } },
  ...SECTIONS.map(
    (section): KeyBinding => ({
      id: `goto-${section}`,
      keys: [['g', GOTO_KEYS[section]]],
      label: SECTION_LABEL[section],
      group: 'Go to',
      action: { type: 'goto', section },
    }),
  ),
  { id: 'row-next', keys: [['j'], ['ArrowDown']], label: 'Next row', group: 'Lists', action: { type: 'row', move: 'next' } },
  { id: 'row-prev', keys: [['k'], ['ArrowUp']], label: 'Previous row', group: 'Lists', action: { type: 'row', move: 'prev' } },
  { id: 'open', keys: [['Enter']], label: 'Open the active row', group: 'Lists', action: { type: 'open' } },
  { id: 'feedback', keys: [['f'], ['Mod+Shift+q']], label: 'Write a feedback note', group: 'Feedback', action: { type: 'feedback', mode: 'note' }, requires: 'feedback' },
  { id: 'feedback-pick', keys: [['Mod+Shift+f']], label: 'Pin feedback to an element', group: 'Feedback', action: { type: 'feedback', mode: 'pick' }, requires: 'feedback', global: true },
  { id: 'feedback-recent', keys: [['Mod+Shift+t']], label: 'Recent feedback', group: 'Feedback', action: { type: 'feedback', mode: 'recent' }, requires: 'feedback', global: true },
]

export const CHORD_MS = 1200

export interface KeyInput {
  /** KeyboardEvent.key */
  key: string
  /** Cmd or Ctrl held. */
  mod: boolean
  /** Shift held; only distinguishes Cmd/Ctrl chords (`?` arrives as itself). */
  shift?: boolean
  alt: boolean
  /** Focus is in an input, textarea, select or contenteditable. */
  typing: boolean
  /** A dialog or sheet is open. */
  modal: boolean
  /** Caller's clock in ms (event.timeStamp works). */
  at: number
}

export interface KeymapState {
  pending: readonly string[]
  at: number
}

export const KEYMAP_IDLE: KeymapState = { pending: [], at: 0 }

export interface KeymapResult {
  state: KeymapState
  action: KeyAction | null
  /** True when the key was consumed (an action, or the start of a chord): call preventDefault. */
  handled: boolean
}

/** The token a key press matches in KEYMAP: `Mod+k`, `g`, `?`, `ArrowDown`. */
export function keyToken(key: string, mod: boolean, shift = false): string {
  // Shift is not folded: `G` (Shift+g) is not `g`, while `?` arrives as itself.
  if (!mod) return key
  return `Mod+${shift ? 'Shift+' : ''}${key.toLocaleLowerCase()}`
}

const same = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((t, i) => t === b[i])
const startsWith = (seq: readonly string[], prefix: readonly string[]) => seq.length > prefix.length && prefix.every((t, i) => t === seq[i])

function match(bindings: readonly KeyBinding[], seq: readonly string[]): { exact?: KeyBinding; prefix: boolean } {
  let prefix = false
  for (const b of bindings) {
    for (const s of b.keys) {
      if (same(s, seq)) return { exact: b, prefix: false }
      if (startsWith(s, seq)) prefix = true
    }
  }
  return { prefix }
}

/** Feed one key press through the keymap. */
export function keymapStep(state: KeymapState, input: KeyInput, bindings: readonly KeyBinding[] = KEYMAP): KeymapResult {
  const idle: KeymapResult = { state: KEYMAP_IDLE, action: null, handled: false }
  if (input.alt) return idle
  const token = keyToken(input.key, input.mod, input.shift)
  const blocked = input.typing || input.modal
  const usable = blocked ? bindings.filter((b) => b.global) : bindings
  const live = state.pending.length > 0 && input.at - state.at <= CHORD_MS
  const attempts = live ? [[...state.pending, token], [token]] : [[token]]
  for (const seq of attempts) {
    const m = match(usable, seq)
    if (m.exact) return { state: KEYMAP_IDLE, action: m.exact.action, handled: true }
    if (m.prefix) return { state: { pending: seq, at: input.at }, action: null, handled: true }
  }
  return idle
}

/** Bindings grouped for the shortcuts overlay, in KEYMAP order. */
export function keymapGroups(bindings: readonly KeyBinding[] = KEYMAP, features: readonly KeyFeature[] = []): { group: KeyGroup; bindings: KeyBinding[] }[] {
  const out: { group: KeyGroup; bindings: KeyBinding[] }[] = []
  for (const b of bindings) {
    if (b.requires && !features.includes(b.requires)) continue
    const g = out.find((x) => x.group === b.group)
    if (g) g.bindings.push(b)
    else out.push({ group: b.group, bindings: [b] })
  }
  return out
}

const KEY_LABEL: Record<string, string> = { ArrowDown: '↓', ArrowUp: '↑', Escape: 'Esc', Backspace: '⌫', Enter: '↵' }

/** Display form of one key token: `Mod+k` is `⌘K` on Apple platforms and `Ctrl K` elsewhere. */
export function keyLabel(token: string, apple = true): string {
  if (token.startsWith('Mod+')) {
    const shift = token.startsWith('Mod+Shift+')
    const k = token.slice(shift ? 10 : 4).toLocaleUpperCase()
    if (apple) return `${shift ? '⇧' : ''}⌘${k}`
    return `Ctrl ${shift ? 'Shift ' : ''}${k}`
  }
  return KEY_LABEL[token] ?? (token.length === 1 ? token.toLocaleUpperCase() : token)
}

/** Display form of a sequence: `G E`. */
export function sequenceLabel(seq: readonly string[], apple = true): string {
  return seq.map((t) => keyLabel(t, apple)).join(' ')
}

/** The first sequence bound to an action, for hints such as the palette's `G E`. */
export function shortcutFor(action: KeyAction, apple = true, bindings: readonly KeyBinding[] = KEYMAP): string | undefined {
  const b = bindings.find((x) => JSON.stringify(x.action) === JSON.stringify(action))
  const first = b?.keys[0]
  return first ? sequenceLabel(first, apple) : undefined
}
