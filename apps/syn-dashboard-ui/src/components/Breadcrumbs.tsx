import { ChevronRight, Home } from 'lucide-react'
import { Link } from 'react-router-dom'

export interface BreadcrumbItem {
  label: string
  href?: string
}

interface BreadcrumbsProps {
  items: BreadcrumbItem[]
}

export function Breadcrumbs({ items }: BreadcrumbsProps) {
  return (
    <nav className="flex items-center gap-1 text-sm text-[var(--color-text-muted)]">
      <Link
        to="/"
        className="flex items-center gap-1 hover:text-[var(--color-text-secondary)] transition-colors"
      >
        <Home className="h-4 w-4" />
      </Link>
      {items.map((item, index) => (
        <div key={index} className="flex items-center gap-1">
          <ChevronRight className="h-4 w-4 text-[var(--color-text-muted)]" />
          {item.href ? (
            <Link
              to={item.href}
              className="hover:text-[var(--color-text-secondary)] transition-colors truncate max-w-[200px]"
              title={item.label}
            >
              {item.label}
            </Link>
          ) : (
            <span className="text-[var(--color-text-primary)] font-medium truncate max-w-[200px]" title={item.label}>
              {item.label}
            </span>
          )}
        </div>
      ))}
    </nav>
  )
}
