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
  const { row, col } = nextCell(s, e)
  return row === s.row && col === s.col ? s : { ...s, row, col }
}

/** The cell an event (other than resize) moves the cursor to. */
function nextCell(s: GridCursorState, e: Exclude<GridCursorEvent, { type: 'resize' }>): { row: number; col: number } {
  switch (e.type) {
    case 'move':
      return { row: clamp(s.row + e.dRow, s.rows), col: clamp(s.col + e.dCol, s.cols) }
    case 'home':
      return { row: e.grid ? 0 : s.row, col: 0 }
    case 'end':
      return { row: e.grid ? s.rows - 1 : s.row, col: s.cols - 1 }
    case 'pick':
      return { row: clamp(e.row, s.rows), col: clamp(e.col, s.cols) }
  }
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
