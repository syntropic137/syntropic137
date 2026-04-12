import { Activity, Container, FileText } from 'lucide-react'
import { Link } from 'react-router-dom'
import { StatusBadge } from '../../components'
import type { SessionResponse } from '../../types'
import { PROVIDER_ENVIRONMENTS } from './sessionConstants'

function WorkspaceEnvironmentBadge({ provider }: { provider: string | null }) {
  if (!provider) return null
  const env = PROVIDER_ENVIRONMENTS[provider.toLowerCase()]
  const label = env ? `${env.backend}:${env.image}` : provider
  return (
    <span className="flex items-center gap-1.5">
      <Container className="h-3.5 w-3.5" />
      <code className="font-mono">{label}</code>
    </span>
  )
}

export function SessionHeader({
  session,
  onViewConversationLog,
}: {
  session: SessionResponse
  onViewConversationLog: () => void
}) {
  const logAvailable = session.status === 'completed' || session.status === 'failed'
  return (
    <div>
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20">
            <Activity className="h-6 w-6 text-emerald-400" />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-[var(--color-text-primary)]">
                {session.workflow_name ?? session.id.slice(0, 16) + '...'}
              </h1>
              <StatusBadge status={session.status} size="lg" pulse />
            </div>
            <div className="mt-2 flex items-center gap-4 text-sm text-[var(--color-text-secondary)]">
              <span className="font-mono">{session.id.slice(0, 12)}</span>
              {session.workflow_id && (
                <Link
                  to={`/workflows/${session.workflow_id}`}
                  className="hover:text-[var(--color-accent)]"
                >
                  {session.workflow_name ? `Workflow: ${session.workflow_name}` : `wf:${session.workflow_id.slice(0, 8)}`}
                </Link>
              )}
              {session.phase_id && <span>Phase: {session.phase_id}</span>}
            </div>
            <div className="mt-1 flex items-center gap-4 text-xs text-[var(--color-text-muted)]">
              <WorkspaceEnvironmentBadge provider={session.agent_provider} />
            </div>
          </div>
        </div>

        <button
          onClick={onViewConversationLog}
          disabled={!logAvailable}
          title={logAvailable ? undefined : 'Transcript available after session completes'}
          className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm transition-colors ${
            logAvailable
              ? 'bg-[var(--color-surface-elevated)] text-[var(--color-text-secondary)] hover:bg-[var(--color-accent)] hover:text-white cursor-pointer'
              : 'bg-[var(--color-surface-elevated)] text-[var(--color-text-muted)] opacity-50 cursor-not-allowed'
          }`}
        >
          <FileText className="h-4 w-4" />
          {logAvailable ? 'View Transcript' : 'Transcript available after completion'}
        </button>
      </div>
    </div>
  )
}
