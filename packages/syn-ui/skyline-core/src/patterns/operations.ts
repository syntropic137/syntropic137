/**
 * Operation Timeline (Session board): one row per tool call, start and
 * finish merged, errors in coral, with copy buttons for input and output.
 */
import { GLYPH } from './glyphs'

export type OperationStatus = 'ok' | 'failed' | 'running' | 'quiet'

export interface Operation {
  id: string
  /** Clock time as shown: "1:32:36 PM". */
  time: string
  /** "Bash", "Edit", "Read". */
  tool: string
  /** The command, path or argument summary; copied by the input button. */
  input: string
  output?: string | null
  status: OperationStatus
  /** "0s", "6s". */
  duration?: string
  /** A hand-off to another agent: "Handed off to Claude · child session 35468ba1". */
  delegated?: { agent: string; agentKind?: 'claude' | 'codex' | 'other'; label: string; id?: string; href?: string } | null
}

/** Glyph path for a tool name. */
export function toolGlyph(tool: string): string {
  const t = tool.toLowerCase()
  if (t === 'bash' || t === 'shell' || t.includes('exec') || t === 'command') return GLYPH.terminal
  if (t === 'edit' || t === 'write' || t === 'multiedit' || t.includes('patch')) return GLYPH.edit
  if (t === 'read' || t === 'notebookread') return GLYPH.file
  if (t === 'grep' || t === 'glob' || t.includes('search')) return GLYPH.search
  if (t.startsWith('web')) return GLYPH.globe
  if (t === 'task' || t === 'agent') return GLYPH.agent
  if (t === 'capture' || t.includes('complete')) return GLYPH.check
  return GLYPH.tool
}

/** "failed · 0s", "ok · 6s", "running", or nothing for quiet rows. */
export function operationStatusText(op: Pick<Operation, 'status' | 'duration'>): string {
  switch (op.status) {
    case 'quiet':
      return ''
    case 'running':
      return 'running'
    case 'failed':
      return `failed · ${op.duration ?? '0s'}`
    case 'ok':
      return `ok · ${op.duration ?? '0s'}`
  }
}

/** Plain text for "Copy all": time, tool and input on one line, output beneath, blank line between. */
export function operationsToText(ops: readonly Operation[]): string {
  return ops.map((o) => `${o.time}  ${o.tool}  ${o.input}${o.output ? `\n${o.output}` : ''}`).join('\n\n')
}

/** Lines shown before an output folds behind "Show all". */
export const OUTPUT_PREVIEW_LINES = 8

/** Split an output into what shows folded and how many lines hide. */
export function foldOutput(output: string, lines = OUTPUT_PREVIEW_LINES): { preview: string; hidden: number } {
  const all = output.split('\n')
  if (all.length <= lines) return { preview: output, hidden: 0 }
  return { preview: all.slice(0, lines).join('\n'), hidden: all.length - lines }
}
