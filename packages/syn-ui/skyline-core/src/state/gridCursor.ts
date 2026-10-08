import type { Reducer } from './machine'

/**
 * A selected cell in a grid (Verdict Board: cases down, verifiers across).
 * Arrow keys move without wrapping; Home and End jump within the row, and
 * with `ctrl` to the first or last cell of the grid.
 */
export interface GridCursorState {
  row: number
  col: number
  rows: number
  cols: number
}

export type GridCursorEvent =
  | { type: 'move'; dRow: number; dCol: number }
  | { type: 'home'; grid?: boolean }
  | { type: 'end'; grid?: boolean }
  | { type: 'pick'; row: number; col: number }
  | { type: 'resize'; rows: number; cols: number }

const clamp = (v: number, max: number) => Math.max(0, Math.min(max - 1, v))

export const gridCursor: Reducer<GridCursorState, GridCursorEvent> = (s, e) => {
  if (e.type === 'resize') return { rows: e.rows, cols: e.cols, row: clamp(s.row, Math.max(1, e.rows)), col: clamp(s.col, Math.max(1, e.cols)) }
  if (s.rows <= 0 || s.cols <= 0) return s
  let { row, col } = s
  switch (e.type) {
    case 'move':
      row = clamp(row + e.dRow, s.rows)
      col = clamp(col + e.dCol, s.cols)
      break
    case 'home':
      col = 0
      if (e.grid) row = 0
      break
    case 'end':
      col = s.cols - 1
      if (e.grid) row = s.rows - 1
      break
    case 'pick':
      row = clamp(e.row, s.rows)
      col = clamp(e.col, s.cols)
      break
  }
  return row === s.row && col === s.col ? s : { ...s, row, col }
}

/** Map a keydown to a cursor event; null leaves the key alone. */
export function gridKey(key: string, ctrl = false): GridCursorEvent | null {
  switch (key) {
    case 'ArrowLeft':
      return { type: 'move', dRow: 0, dCol: -1 }
    case 'ArrowRight':
      return { type: 'move', dRow: 0, dCol: 1 }
    case 'ArrowUp':
      return { type: 'move', dRow: -1, dCol: 0 }
    case 'ArrowDown':
      return { type: 'move', dRow: 1, dCol: 0 }
    case 'Home':
      return { type: 'home', grid: ctrl }
    case 'End':
      return { type: 'end', grid: ctrl }
    default:
      return null
  }
}
