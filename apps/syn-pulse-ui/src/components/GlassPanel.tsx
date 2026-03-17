import clsx from 'clsx'
import type { ReactNode } from 'react'

interface GlassPanelProps {
  children: ReactNode
  className?: string
}

export function GlassPanel({ children, className }: GlassPanelProps) {
  return (
    <div className={clsx('glass-panel p-6', className)}>
      {children}
    </div>
  )
}
