import {
  Clock,
  GitBranch,
  GitCommit,
  MessageSquare,
  Zap,
} from 'lucide-react'
import type { OperationInfo } from '../../types'
import { formatDurationSeconds } from '../../utils/formatters'

function GitBadges({ op }: { op: OperationInfo }) {
  return (
    <>
      {op.git_message && (
        <span className="flex items-center gap-1 max-w-sm truncate">
          <GitCommit className="h-3 w-3 shrink-0" />
          {op.git_message}
        </span>
      )}
      {op.git_sha && (
        <span className="font-mono text-[var(--color-text-muted)]">{op.git_sha.slice(0, 7)}</span>
      )}
      {(op.git_repo || op.git_branch) && (
        <span className="flex items-center gap-1 font-mono">
          <GitBranch className="h-3 w-3" />
          {op.git_repo && op.git_branch ? `${op.git_repo}/${op.git_branch}` : op.git_repo || op.git_branch}
        </span>
      )}
    </>
  )
}

export function OperationMetaBadges({ op }: { op: OperationInfo }) {
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-text-secondary)]">
      <GitBadges op={op} />
      {op.message_role && (
        <span className="flex items-center gap-1">
          <MessageSquare className="h-3 w-3" />
          {op.message_role}
        </span>
      )}
      {op.total_tokens !== null && op.total_tokens > 0 && (
        <span className="flex items-center gap-1">
          <Zap className="h-3 w-3" />
          {op.total_tokens.toLocaleString()} tokens
        </span>
      )}
      {op.duration_seconds !== null && (
        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {formatDurationSeconds(op.duration_seconds)}
        </span>
      )}
    </div>
  )
}
