import type { Reducer } from './machine'

/**
 * IsoCity scroll as one continuous glide (owner, Oct 10: "not just move and
 * immediately disappear"). The floor stays laid out around `anchor` (the
 * window it last landed on) while it translates by `shift` weeks toward the
 * target; the data window moves to the target only when the glide lands, so
 * nothing re-paints mid-glide. A new target while gliding retargets: the
 * anchor stays, only the shift changes, so a CSS transition carries on from
 * wherever it is (no jump back). `pad` weeks of buffer are laid out either
 * side so blocks have somewhere to fade in from.
 *
 * Reduced motion lands at once (the component crossfades). No timers here:
 * the component lands on transitionend, with a timeout as the backstop.
 */
export interface IsoGlideState {
  /** Week index the floor is laid out around; null before the first target. */
  anchor: number | null
  /** Weeks of translation (content moves right for positive). 0 at rest. */
  shift: number
  /** A CSS transition is carrying the shift. */
  gliding: boolean
  dragging: boolean
  /** Weeks laid out either side of the window. */
  pad: number
  /** Where the shift stood when the drag began (the displayed position, mid-glide included). */
  dragFrom: number
}

export type IsoGlideEvent =
  /** The window should show week `first` (offset changed). */
  | { type: 'target'; first: number; reduced: boolean }
  /** The glide reached its target (transitionend or the backstop). */
  | { type: 'land'; first: number }
  /**
   * A drag or swipe is `weeks` from where it started; `first` is the current
   * window. `from` is the shift on screen when the drag began (a glide in
   * flight is mid-transition), so a drag never snaps.
   */
  | { type: 'drag'; weeks: number; first: number; from?: number }
  /** The drag ended over window `first`: glide there (a 'target' may follow), or land at once under reduced motion. */
  | { type: 'release'; first: number; reduced: boolean }

/** Buffer weeks each side at rest: something to fade in from at the edges. */
export const ISO_GLIDE_BUFFER = 2

export const initialIsoGlide: IsoGlideState = { anchor: null, shift: 0, gliding: false, dragging: false, pad: ISO_GLIDE_BUFFER, dragFrom: 0 }

const landed = (first: number): IsoGlideState => ({ anchor: first, shift: 0, gliding: false, dragging: false, pad: ISO_GLIDE_BUFFER, dragFrom: 0 })
const padFor = (weeks: number) => Math.max(ISO_GLIDE_BUFFER, Math.ceil(Math.abs(weeks)) + ISO_GLIDE_BUFFER)

function toTarget(s: IsoGlideState, first: number, reduced: boolean): IsoGlideState {
  if (s.anchor === null || reduced) return landed(first)
  if (s.dragging) return s
  const shift = s.anchor - first
  if (shift === 0 && s.shift === 0) return landed(first)
  return { ...s, shift, gliding: true, pad: Math.max(s.pad, padFor(shift)) }
}

/** Where a new drag starts: mid-glide it keeps the anchor and the displayed shift; at rest it lands first. */
function dragStart(s: IsoGlideState, first: number, from: number | undefined): IsoGlideState {
  if (s.anchor === null || (!s.gliding && s.shift === 0)) return landed(first)
  return { ...s, dragFrom: from ?? s.shift }
}

function drag(s: IsoGlideState, weeks: number, first: number, from: number | undefined): IsoGlideState {
  const base = s.dragging ? s : dragStart(s, first, from)
  const shift = base.dragFrom + weeks
  return { ...base, dragging: true, gliding: false, shift, pad: Math.max(base.pad, padFor(shift)) }
}

function release(s: IsoGlideState, first: number, reduced: boolean): IsoGlideState {
  if (s.anchor === null || reduced) return landed(first)
  const shift = s.anchor - first
  if (shift === 0 && s.shift === 0) return landed(first)
  return { ...s, dragging: false, gliding: true, shift, pad: Math.max(s.pad, padFor(shift)) }
}

export const isoGlide: Reducer<IsoGlideState, IsoGlideEvent> = (s, e) => {
  if (e.type === 'target') return toTarget(s, e.first, e.reduced)
  if (e.type === 'land') return landed(e.first)
  if (e.type === 'drag') return drag(s, e.weeks, e.first, e.from)
  return release(s, e.first, e.reduced)
}

/** How far the drag itself has moved, in weeks (excluding where it started). */
export function dragWeeks(s: IsoGlideState): number {
  return s.dragging ? s.shift - s.dragFrom : 0
}

/** The window the eye is heading for: where a drag points, else the target. Blocks outside it fade. */
export function glideFocusFirst(s: IsoGlideState, first: number): number {
  return s.dragging && s.anchor !== null ? s.anchor - Math.round(s.shift) : first
}
