import { clsx } from 'clsx'
import {
  Box,
  CheckCircle2,
  Cloud,
  Container,
  Cpu,
  HardDrive,
  Loader2,
  Server,
  Shield,
  Terminal,
  XCircle,
} from 'lucide-react'

import type { IsolationBackend, WorkspaceInfo } from '../types'

import { Card, CardContent, CardHeader } from './Card'

interface WorkspaceInfoCardProps {
  workspace: WorkspaceInfo | null
  isLoading?: boolean
}

const backendIcons: Record<IsolationBackend, typeof Container> = {
  docker_hardened: Container,
  gvisor: Shield,
  firecracker: Server,
  kata: Box,
  cloud: Cloud,
  local: HardDrive,
}

const backendLabels: Record<IsolationBackend, string> = {
  docker_hardened: 'Docker (Hardened)',
  gvisor: 'gVisor',
  firecracker: 'Firecracker',
  kata: 'Kata Containers',
  cloud: 'Cloud Sandbox',
  local: 'Local (Dev Only)',
}

const backendColors: Record<IsolationBackend, string> = {
  docker_hardened: 'text-blue-400',
  gvisor: 'text-emerald-400',
  firecracker: 'text-orange-400',
  kata: 'text-purple-400',
  cloud: 'text-cyan-400',
  local: 'text-yellow-400',
}

const statusColors: Record<string, string> = {
  creating: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  running: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  stopped: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
  error: 'bg-red-500/20 text-red-400 border-red-500/30',
}

const statusIcons: Record<string, typeof CheckCircle2> = {
  creating: Loader2,
  running: CheckCircle2,
  stopped: Box,
  error: XCircle,
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function WorkspaceEmptyState() {
  return (
    <Card>
      <CardHeader title="Workspace" subtitle="Isolated execution environment" />
      <CardContent>
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <Container className="h-8 w-8 text-[var(--color-text-muted)] mb-2" />
          <p className="text-sm text-[var(--color-text-muted)]">No workspace assigned yet</p>
        </div>
      </CardContent>
    </Card>
  )
}

function WorkspaceContent({ workspace }: { workspace: WorkspaceInfo }) {
  const BackendIcon = backendIcons[workspace.isolation_backend] ?? Container
  const StatusIcon = statusIcons[workspace.status] ?? Box
  const isolationId = workspace.container_id || workspace.vm_id || workspace.sandbox_id || 'N/A'

  return (
    <CardContent className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BackendIcon className={clsx('h-5 w-5', backendColors[workspace.isolation_backend])} />
          <span className="text-sm font-medium text-[var(--color-text-primary)]">
            {backendLabels[workspace.isolation_backend]}
          </span>
        </div>
        <span
          className={clsx(
            'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium border',
            statusColors[workspace.status]
          )}
        >
          <StatusIcon className={clsx('h-3 w-3', workspace.status === 'creating' && 'animate-spin')} />
          {workspace.status.charAt(0).toUpperCase() + workspace.status.slice(1)}
        </span>
      </div>

      <div className="flex items-center gap-2 rounded-lg bg-[var(--color-surface)] p-3 border border-[var(--color-border)]">
        <Terminal className="h-4 w-4 text-[var(--color-text-muted)]" />
        <code className="text-xs font-mono text-[var(--color-text-secondary)] break-all">
          {isolationId.slice(0, 12)}
        </code>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-[var(--color-surface)] p-3 border border-[var(--color-border)]">
          <div className="flex items-center gap-2 mb-1">
            <HardDrive className="h-3.5 w-3.5 text-[var(--color-text-muted)]" />
            <span className="text-xs text-[var(--color-text-muted)]">Memory</span>
          </div>
          <span className="text-sm font-medium text-[var(--color-text-primary)]">
            {formatBytes(workspace.memory_used_bytes)}
          </span>
        </div>
        <div className="rounded-lg bg-[var(--color-surface)] p-3 border border-[var(--color-border)]">
          <div className="flex items-center gap-2 mb-1">
            <Cpu className="h-3.5 w-3.5 text-[var(--color-text-muted)]" />
            <span className="text-xs text-[var(--color-text-muted)]">CPU Time</span>
          </div>
          <span className="text-sm font-medium text-[var(--color-text-primary)]">
            {workspace.cpu_time_seconds.toFixed(2)}s
          </span>
        </div>
      </div>

      <div className="flex items-center justify-between text-sm">
        <span className="text-[var(--color-text-muted)]">Commands Executed</span>
        <span className="font-medium text-[var(--color-text-primary)]">{workspace.commands_executed}</span>
      </div>

      <div className="text-xs text-[var(--color-text-muted)]">
        <span className="opacity-60">Path: </span>
        <code className="font-mono">{workspace.workspace_path}</code>
      </div>
    </CardContent>
  )
}

export function WorkspaceInfoCard({ workspace, isLoading }: WorkspaceInfoCardProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader title="Workspace" subtitle="Isolated execution environment" />
        <CardContent>
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-[var(--color-text-muted)]" />
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!workspace) return <WorkspaceEmptyState />

  return (
    <Card>
      <CardHeader title="Workspace" subtitle="Isolated execution environment" />
      <WorkspaceContent workspace={workspace} />
    </Card>
  )
}
