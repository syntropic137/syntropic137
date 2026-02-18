import { clsx } from 'clsx'
import {
  Activity,
  Bell,
  Box,
  FileText,
  GitBranch,
  LayoutDashboard,
  Settings,
  Zap,
} from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'

const navigation = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
  { name: 'Workflows', href: '/workflows', icon: GitBranch },
  { name: 'Executions', href: '/executions', icon: Zap },
  { name: 'Sessions', href: '/sessions', icon: Activity },
  { name: 'Artifacts', href: '/artifacts', icon: FileText },
  { name: 'Triggers', href: '/triggers', icon: Bell },
]

export function Layout() {
  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="fixed inset-y-0 left-0 z-10 flex w-56 flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)]">
        {/* Logo */}
        <div className="flex h-14 items-center gap-2 border-b border-[var(--color-border)] px-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600">
            <Zap className="h-4 w-4 text-white" />
          </div>
          <div>
            <span className="text-sm font-bold text-[var(--color-text-primary)]">syn137</span>
            <span className="ml-1 text-xs text-[var(--color-text-secondary)]">Dashboard</span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 p-3">
          {navigation.map((item) => (
            <NavLink
              key={item.name}
              to={item.href}
              end={item.href === '/'}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
                    : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-elevated)] hover:text-[var(--color-text-primary)]'
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {item.name}
            </NavLink>
          ))}
        </nav>

        {/* Bottom section */}
        <div className="border-t border-[var(--color-border)] p-3">
          <div className="flex items-center gap-3 rounded-md px-3 py-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--color-surface-elevated)]">
              <Box className="h-3.5 w-3.5 text-[var(--color-text-secondary)]" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="truncate text-xs font-medium text-[var(--color-text-primary)]">
                Local Dev
              </p>
              <p className="truncate text-xs text-[var(--color-text-muted)]">v0.1.0</p>
            </div>
            <button className="rounded p-1 text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-elevated)] hover:text-[var(--color-text-primary)]">
              <Settings className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="ml-56 flex-1">
        <div className="p-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
