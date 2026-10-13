/**
 * Edge train for repo-banner.ts: a repeated line of small mono caps running
 * round the inside of the rounded card, optionally moving counterclockwise
 * (SMIL on startOffset, which runs in an SVG shown through <img>; no JS).
 *
 * One closed path can't keep letters upright on both the top and bottom
 * edges, so the loop is two halves that meet at the middle of each side:
 * the top half (left side up, top left to right, right side down) with
 * glyphs facing outward, and the bottom half (left side down, bottom left
 * to right, right side up) with glyphs facing inward. Both read left to
 * right; counterclockwise travel is the top half's offset falling and the
 * bottom half's rising. Both glyph bands sit the same distance from the
 * border.
 */
import { measure, type StaticFont } from './fontSubset.ts'

export interface EdgeTrainOptions {
  width: number
  height: number
  radius: number
  text: string
  /** Seconds for the train to move one repeat of `text`; 0 for a still frame. */
  seconds: number
  font: StaticFont
  family: string
  fill: string
  accent: string
}

const SIZE = 10.5
const TRACKING = 0.16
const CAP = 0.73
/** Gap between the card edge and the nearest side of the glyph band. */
const MARGIN = 7
const SEPARATOR = ' · '

const n = (v: number) => Math.round(v * 100) / 100

function halfPaths(w: number, h: number, radius: number): { top: string; bottom: string; length: number } {
  const dTop = MARGIN + SIZE * CAP
  const rTop = radius - dTop
  const dBot = MARGIN
  const rBot = radius - dBot
  const top = `M${n(dTop)} ${h / 2}V${n(dTop + rTop)}A${n(rTop)} ${n(rTop)} 0 0 1 ${n(dTop + rTop)} ${n(dTop)}H${n(w - dTop - rTop)}A${n(rTop)} ${n(rTop)} 0 0 1 ${n(w - dTop)} ${n(dTop + rTop)}V${h / 2}`
  const bottom = `M${n(dBot)} ${h / 2}V${n(h - dBot - rBot)}A${n(rBot)} ${n(rBot)} 0 0 0 ${n(dBot + rBot)} ${n(h - dBot)}H${n(w - dBot - rBot)}A${n(rBot)} ${n(rBot)} 0 0 0 ${n(w - dBot)} ${n(h - dBot - rBot)}V${h / 2}`
  const length = w + h // generous: a half is under (w + h - corners)
  return { top, bottom, length }
}

/** The repeat unit, its advance width and enough repeats to cover a half plus one unit of travel. */
function stream(o: EdgeTrainOptions, length: number): { unit: string; advance: number; text: string } {
  const unit = `${o.text.toUpperCase()}${SEPARATOR}`
  const advance = measure(o.font, unit, SIZE, TRACKING)
  const repeats = Math.ceil((length + advance) / advance) + 1
  return { unit, advance, text: unit.repeat(repeats) }
}

function spans(text: string, unit: string, accent: string): string {
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
  const body = esc(unit.slice(0, -SEPARATOR.length))
  const one = `${body} <tspan fill="${accent}">·</tspan> `
  return one.repeat(Math.round(text.length / unit.length))
}

function textPath(id: string, content: string, from: number, to: number, seconds: number): string {
  const anim = seconds > 0 ? `<animate attributeName="startOffset" from="${n(from)}" to="${n(to)}" dur="${seconds}s" repeatCount="indefinite"/>` : ''
  return `<textPath href="#${id}" startOffset="${n(from)}">${content}${anim}</textPath>`
}

/**
 * Fade the train out round each corner (tight arcs fan the glyphs) and at
 * the middle of each side (where the halves meet and the glyphs flip).
 */
function fadeMask(w: number, h: number): string {
  const hole = (cx: number, cy: number, rx: number, ry: number) => `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="url(#train-hole)"/>`
  const corners = [[0, 0], [w, 0], [0, h], [w, h]].map(([x, y]) => hole(x ?? 0, y ?? 0, 70, 56)).join('')
  const joins = hole(0, h / 2, 40, 64) + hole(w, h / 2, 40, 64)
  return `<radialGradient id="train-hole"><stop offset="0.45" stop-color="#000"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient><mask id="train-mask" maskUnits="userSpaceOnUse" x="0" y="0" width="${w}" height="${h}"><rect width="${w}" height="${h}" fill="#fff"/>${corners}${joins}</mask>`
}

/** Path defs plus the two text runs. */
export function edgeTrain(o: EdgeTrainOptions): { defs: string; body: string; glyphs: string } {
  const p = halfPaths(o.width, o.height, o.radius)
  const s = stream(o, p.length)
  const content = spans(s.text, s.unit, o.accent)
  const attrs = `font-family="${o.family}" font-size="${SIZE}" font-weight="500" letter-spacing="${TRACKING}em" fill="${o.fill}" xml:space="preserve"`
  const defs = `<path id="train-top" d="${p.top}"/><path id="train-bottom" d="${p.bottom}"/>${fadeMask(o.width, o.height)}`
  // Top half: offset falls from 0 to -advance (travel toward the left-side join).
  // Bottom half: offset rises from -advance to 0 (travel away from it).
  const body = `<g mask="url(#train-mask)" opacity="0.66" ${attrs}><text>${textPath('train-top', content, 0, -s.advance, o.seconds)}</text><text>${textPath('train-bottom', content, -s.advance, 0, o.seconds)}</text></g>`
  return { defs, body, glyphs: s.unit }
}
