/**
 * Tool-log ticker (Landing pillar 03; later the app's live execution view):
 * recent tool calls scrolling past in a masked box. Ported from
 * observe_visual() in design/reference/gen_landing4.py.
 *
 * The rows render twice and the list scrolls by one copy, so the loop is
 * seamless. Energy rule (landing plan, section 7): the ticker plays only
 * while visible and stops after about TOOL_LOG_PLAY_SECONDS of playing.
 */

export interface ToolLogRow {
  /** Clock time of the call: "14:02:11". */
  time: string
  /** Tool name: "Read", "Bash". */
  tool: string
  /** What it touched: a path, a command, a pattern. */
  target: string
  /** How long it took, as shown: "42ms", "8.4s". */
  duration: string
}

export interface ToolLogProps {
  rows: readonly ToolLogRow[]
  /** Seconds each row takes to scroll past (default TOOL_LOG_SPEED); 0 keeps the log still. */
  speed?: number
  /** Accessible name (default "Recent tool calls"). */
  label?: string
}

/** Seconds per row on the board: 8 rows in 14s. */
export const TOOL_LOG_SPEED = 1.75
/** Total play time the ticker aims for before it stops. */
export const TOOL_LOG_PLAY_SECONDS = 20

export interface TickerTiming {
  /** False when there is nothing to scroll or speed is 0: render the rows still. */
  moving: boolean
  /** Seconds for one pass over the rows. */
  duration: number
  /** Passes to play; duration * iterations stays close to TOOL_LOG_PLAY_SECONDS, at least one pass. */
  iterations: number
}

/** How long one pass takes and how many to play, from the row count and speed. */
export function tickerTiming(rows: number, speed: number = TOOL_LOG_SPEED, playSeconds: number = TOOL_LOG_PLAY_SECONDS): TickerTiming {
  const s = Number.isFinite(speed) && speed > 0 ? speed : 0
  if (rows < 2 || s === 0) return { moving: false, duration: 0, iterations: 0 }
  const duration = Math.round(rows * s * 100) / 100
  return { moving: true, duration, iterations: Math.max(1, Math.round(playSeconds / duration)) }
}
