/**
 * The dialog appends what FeedbackCreate has no field for under a `---` line
 * (`element: h1 "Executions" at 185,174 335x46`, `theme: syn137`). Split it
 * back out for the detail view.
 */
const FOOTER = '\n\n---\n'

export interface ParsedComment {
  body: string
  /** `element` line minus the box: `h1 "Executions"`. */
  element: string | null
  meta: Record<string, string>
}

export function parseComment(comment: string | null | undefined): ParsedComment {
  const text = comment ?? ''
  const at = text.lastIndexOf(FOOTER)
  if (at < 0) return { body: text, element: null, meta: {} }
  const meta: Record<string, string> = {}
  for (const line of text.slice(at + FOOTER.length).split('\n')) {
    const i = line.indexOf(': ')
    if (i > 0) meta[line.slice(0, i)] = line.slice(i + 2)
  }
  const el = meta.element ?? null
  return { body: text.slice(0, at), element: el ? el.replace(/ at \d+,\d+ \d+x\d+$/, '') : null, meta }
}
