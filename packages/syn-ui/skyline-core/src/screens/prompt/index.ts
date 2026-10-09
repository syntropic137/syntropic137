/**
 * Prompt and task text as body copy (feedback 525d15c0): the small Markdown
 * subset agents' prompts use, parsed into display blocks. Shared by the
 * Workflow detail (phase prompt templates) and the Execution detail (the
 * task). Headings are labels at the block's own text scale, never page
 * headings; lists keep their order and one level of nesting; fenced code and
 * `inline code` render in mono.
 */

export interface PromptListItem {
  text: string
  /** Indented items under this one (deeper levels flatten into this list). */
  items: string[]
}

export type PromptBlock =
  | { kind: 'heading'; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'list'; ordered: boolean; items: PromptListItem[] }
  | { kind: 'code'; text: string }
  | { kind: 'argument'; name: string }

export type PromptSpan = { kind: 'text' | 'code' | 'strong'; text: string }

/**
 * Split a prompt into display blocks: "#" headings, "-"/"*"/"+" and "1."
 * lists (indented items nest one level), ``` fences, a line that is only
 * `$ARGUMENTS` or `{{task}}` becomes the argument slot, everything else
 * paragraphs (soft-wrapped lines join with a space).
 */
export function parsePrompt(template: string | null | undefined): PromptBlock[] {
  const acc = new PromptAccumulator()
  for (const raw of (template ?? '').replace(/\r\n?/g, '\n').split('\n')) acc.line(raw)
  acc.end()
  return acc.blocks
}

/** Inline `code` and **strong** runs of one block's text. Unclosed markers stay literal. */
export function inlineSpans(text: string): PromptSpan[] {
  const out: PromptSpan[] = []
  const re = /`([^`]+)`|\*\*([^*]+)\*\*/g
  let last = 0
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push({ kind: 'text', text: text.slice(last, m.index) })
    out.push(m[1] !== undefined ? { kind: 'code', text: m[1] } : { kind: 'strong', text: m[2]! })
    last = m.index + m[0].length
  }
  if (last < text.length) out.push({ kind: 'text', text: text.slice(last) })
  return out
}

export interface TaskParts {
  /** One line for the page title. */
  title: string
  /** The rest (or all of it, when the title had to be clipped) as body copy; empty for a one-liner. */
  body: string
}

/** Longest task first line that stays a title; past it the title is clipped and the body carries the whole task. */
export const TASK_TITLE_MAX = 120

/**
 * A task is often a whole prompt. Its first line (Markdown heading marks
 * dropped) is the page title; everything else renders as body copy.
 */
export function splitTask(task: string | null | undefined): TaskParts {
  const text = (task ?? '').replace(/\r\n?/g, '\n').trim()
  if (!text) return { title: '', body: '' }
  const nl = text.indexOf('\n')
  const first = (nl < 0 ? text : text.slice(0, nl)).replace(/^#{1,6}\s+/, '').trim()
  const rest = nl < 0 ? '' : text.slice(nl + 1).trim()
  if (first.length <= TASK_TITLE_MAX) return { title: first, body: rest }
  const cut = first.slice(0, TASK_TITLE_MAX)
  const space = cut.lastIndexOf(' ')
  return { title: `${(space > TASK_TITLE_MAX / 2 ? cut.slice(0, space) : cut).trimEnd()}…`, body: text }
}

const PROMPT_ARGUMENT = /^(\$[A-Z_]+|\{\{\s*[a-z_]+\s*\}\})$/
const PROMPT_HEADING = /^#{1,6}\s+(.*)$/
const PROMPT_LIST_ITEM = /^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$/
const PROMPT_FENCE = /^\s*```/

/** parsePrompt's line state: the open paragraph, list and code fence. */
class PromptAccumulator {
  readonly blocks: PromptBlock[] = []
  private para: string[] = []
  private list: { ordered: boolean; items: PromptListItem[] } | null = null
  private code: string[] | null = null

  line(raw: string): void {
    if (this.code) {
      if (PROMPT_FENCE.test(raw)) this.closeCode()
      else this.code.push(raw)
      return
    }
    if (PROMPT_FENCE.test(raw)) {
      this.flush()
      this.code = []
      return
    }
    const line = raw.trim()
    if (!line) {
      this.flushParagraph()
      return
    }
    const li = PROMPT_LIST_ITEM.exec(raw)
    if (li) {
      this.listItem(li[1]!.length > 0, /\d/.test(li[2]!), li[3]!)
      return
    }
    // An indented line under an open list continues its last item.
    if (this.list && /^\s/.test(raw) && !this.para.length) {
      this.continueItem(line)
      return
    }
    this.flushList()
    const arg = PROMPT_ARGUMENT.exec(line)
    if (arg) {
      this.block({ kind: 'argument', name: arg[1]!.replace(/[{}\s]/g, '') })
      return
    }
    const h = PROMPT_HEADING.exec(line)
    if (h) this.block({ kind: 'heading', text: h[1]! })
    else this.para.push(line)
  }

  end(): void {
    if (this.code) this.closeCode()
    this.flush()
  }

  private flush(): void {
    this.flushParagraph()
    this.flushList()
  }

  private block(b: PromptBlock): void {
    this.flush()
    this.blocks.push(b)
  }

  private closeCode(): void {
    this.blocks.push({ kind: 'code', text: (this.code ?? []).join('\n') })
    this.code = null
  }

  private flushParagraph(): void {
    if (this.para.length) this.blocks.push({ kind: 'paragraph', text: this.para.join(' ') })
    this.para = []
  }

  private flushList(): void {
    if (this.list) this.blocks.push({ kind: 'list', ...this.list })
    this.list = null
  }

  private listItem(nested: boolean, ordered: boolean, text: string): void {
    this.flushParagraph()
    const last = this.list?.items.at(-1)
    if (nested && last) {
      last.items.push(text)
      return
    }
    if (this.list && this.list.ordered !== ordered) this.flushList()
    ;(this.list ??= { ordered, items: [] }).items.push({ text, items: [] })
  }

  private continueItem(line: string): void {
    const last = this.list!.items.at(-1)!
    if (last.items.length) last.items[last.items.length - 1] += ` ${line}`
    else last.text += ` ${line}`
  }
}
