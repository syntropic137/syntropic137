import type { CSSProperties } from 'react'
import { Tooltip, type TooltipProps } from 'recharts'

const defaultContentStyle: CSSProperties = {
  backgroundColor: 'var(--color-surface-elevated)',
  border: '1px solid var(--color-border)',
  borderRadius: '8px',
  fontSize: '12px',
  color: 'var(--color-text-primary)',
}

const defaultLabelStyle: CSSProperties = {
  color: 'var(--color-text-primary)',
  fontWeight: 600,
  marginBottom: 4,
}

const defaultItemStyle: CSSProperties = {
  color: 'var(--color-text-secondary)',
}

const defaultCursor = { fill: 'rgba(148, 163, 184, 0.08)' }

/**
 * Themed Recharts tooltip with dark-mode defaults.
 * All props are forwarded to Recharts `<Tooltip>` — pass `position`,
 * `offset`, `formatter`, etc. as needed.
 */
export function ChartTooltip(props: TooltipProps<number, string>) {
  const { contentStyle, labelStyle, itemStyle, cursor, ...rest } = props
  return (
    <Tooltip
      cursor={cursor ?? defaultCursor}
      contentStyle={{ ...defaultContentStyle, ...contentStyle }}
      labelStyle={{ ...defaultLabelStyle, ...labelStyle }}
      itemStyle={{ ...defaultItemStyle, ...itemStyle }}
      {...rest}
    />
  )
}
