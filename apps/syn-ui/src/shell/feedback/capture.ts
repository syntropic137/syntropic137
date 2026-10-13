/**
 * Screenshots for the feedback dialog, as the React widget takes them:
 * html2canvas renders the DOM (no browser permission prompt), full page or a
 * dragged area, resized to fit 1920x1080, as PNG. html2canvas-pro is the
 * maintained fork that parses the oklab/color() values our color-mix()
 * tokens compute to (html2canvas 1.4.1 throws on them).
 *
 * Imported dynamically from here only, and this module is reached only from
 * the dev-only feedback chunk, so none of it ships in a production build.
 */
import { FEEDBACK_UI_ATTR } from './element'

export interface Area {
  x: number
  y: number
  width: number
  height: number
}

export interface Shot {
  blob: Blob
  fileName: string
  previewUrl: string
}

const MAX_W = 1920
const MAX_H = 1080

function toBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not encode the screenshot'))), 'image/png'))
}

function fit(src: HTMLCanvasElement, area: Area | null, scale: number): HTMLCanvasElement {
  const sx = area ? area.x * scale : 0
  const sy = area ? area.y * scale : 0
  const sw = area ? area.width * scale : src.width
  const sh = area ? area.height * scale : src.height
  const ratio = Math.min(1, MAX_W / sw, MAX_H / sh)
  const out = document.createElement('canvas')
  out.width = Math.max(1, Math.round(sw * ratio))
  out.height = Math.max(1, Math.round(sh * ratio))
  const ctx = out.getContext('2d')
  if (!ctx) throw new Error('Canvas is unavailable')
  ctx.drawImage(src, sx, sy, sw, sh, 0, 0, out.width, out.height)
  return out
}

/** Capture the visible viewport, or one area of it (viewport coordinates). */
export async function captureViewport(area: Area | null = null): Promise<Shot> {
  const { default: html2canvas } = await import('html2canvas-pro')
  const scale = window.devicePixelRatio || 1
  const canvas = await html2canvas(document.body, {
    useCORS: true,
    logging: false,
    scale,
    x: window.scrollX,
    y: window.scrollY,
    width: window.innerWidth,
    height: window.innerHeight,
    backgroundColor: getComputedStyle(document.body).backgroundColor || null,
    ignoreElements: (el) => el.hasAttribute(FEEDBACK_UI_ATTR) || el.tagName === 'DIALOG',
  })
  const blob = await toBlob(fit(canvas, area, scale))
  return { blob, fileName: `screenshot-${Date.now()}.png`, previewUrl: URL.createObjectURL(blob) }
}

/** An uploaded, pasted or dropped image, re-encoded to PNG when it is larger than 1920x1080. */
export async function fromFile(file: File): Promise<Shot> {
  const bitmap = await createImageBitmap(file)
  const ratio = Math.min(1, MAX_W / bitmap.width, MAX_H / bitmap.height)
  if (ratio === 1) return { blob: file, fileName: file.name || `image-${Date.now()}.png`, previewUrl: URL.createObjectURL(file) }
  const c = document.createElement('canvas')
  c.width = Math.round(bitmap.width * ratio)
  c.height = Math.round(bitmap.height * ratio)
  c.getContext('2d')?.drawImage(bitmap, 0, 0, c.width, c.height)
  const blob = await toBlob(c)
  return { blob, fileName: (file.name || 'image').replace(/\.[^.]+$/, '') + '.png', previewUrl: URL.createObjectURL(blob) }
}
