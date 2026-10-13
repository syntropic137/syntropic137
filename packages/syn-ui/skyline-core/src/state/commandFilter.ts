/**
 * Client-side filtering for the Command palette. Scores an item against the
 * search text; higher is better and 0 means no match.
 *
 *   exact label        1000
 *   label prefix        800
 *   word prefix         600  ("wf" no, "work" in "Research Workflow" yes)
 *   substring           400
 *   keyword match       300
 *   in-order letters    100 minus spread ("rsw" in "Research Workflow")
 */
export interface CommandFilterItem {
  label: string
  /** Extra text that matches but is not shown as the label (slugs, IDs). */
  keywords?: readonly string[]
  disabled?: boolean
}

export interface CommandFilterGroup<T extends CommandFilterItem> {
  heading?: string
  items: readonly T[]
}

export function commandScore(query: string, item: CommandFilterItem): number {
  const q = query.trim().toLocaleLowerCase()
  if (!q) return 1
  const label = item.label.toLocaleLowerCase()
  if (label === q) return 1000
  if (label.startsWith(q)) return 800
  if (label.split(/[\s\-_/:.]+/).some((w) => w.startsWith(q))) return 600
  if (label.includes(q)) return 400
  if (item.keywords?.some((k) => k.toLocaleLowerCase().includes(q))) return 300
  const spread = subsequenceSpread(q, label)
  return spread < 0 ? 0 : Math.max(1, 100 - spread)
}

/** Distance covered matching `q` letter by letter in `text`, or -1 if it does not fit. */
function subsequenceSpread(q: string, text: string): number {
  let first = -1
  let at = -1
  for (const ch of q) {
    if (ch === ' ') continue
    at = text.indexOf(ch, at + 1)
    if (at < 0) return -1
    if (first < 0) first = at
  }
  return at - first - (q.replace(/ /g, '').length - 1)
}

/**
 * Filter and sort each group by score, keeping group order and dropping
 * groups left empty. Ties keep their original order.
 */
export function filterCommandGroups<T extends CommandFilterItem>(
  groups: readonly CommandFilterGroup<T>[],
  query: string,
): CommandFilterGroup<T>[] {
  const out: CommandFilterGroup<T>[] = []
  for (const g of groups) {
    const scored = g.items
      .map((item, i) => ({ item, i, s: commandScore(query, item) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s || a.i - b.i)
      .map((x) => x.item)
    if (scored.length) out.push({ ...g, items: scored })
  }
  return out
}
