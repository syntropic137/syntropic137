/**
 * The heading of a list surface: what this list is, and whether it is live.
 *
 * Sessions and Executions rendered the same nine lines of markup each, which
 * is how the two surfaces came to disagree about everything else (#1159). A
 * page says what its list is called; where the connection state sits and what
 * the heading looks like are not its business.
 *
 * See: docs/adrs/ADR-064-observability-monitor-ui.md
 */

import { ConnectionIndicator } from './ConnectionIndicator'

export interface ListPageHeaderProps {
  title: string
  /** One line under the title saying what the list covers. */
  description: string
  connected: boolean
  lastEventAt: number | null
}

export function ListPageHeader({
  title,
  description,
  connected,
  lastEventAt,
}: ListPageHeaderProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">{title}</h1>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">{description}</p>
      </div>
      <ConnectionIndicator connected={connected} lastEventAt={lastEventAt} />
    </div>
  )
}
