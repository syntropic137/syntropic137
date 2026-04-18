import {
  Clock,
  GitBranch,
  GitCommit,
  MessageSquare,
  Package,
  Zap,
} from 'lucide-react'
import type { OperationInfo } from '../../types'
import { formatDurationSeconds } from '../../utils/formatters'

/**
 * Consistent sub-header for all git operations (commit, push, checkout, merge, etc.).
 * Renders SHA, branch, and repo as separate stacked lines.
 */
function GitOperationMeta({ op }: { op: OperationInfo }) {
  if (!op.git_sha && !op.git_branch && !op.git_repo) return null

  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-text-secondary)]">
      {op.git_sha && (
        <span className="flex items-center gap-1 font-mono">
          <GitCommit className="h-3 w-3 shrink-0" />
          {op.git_sha.slice(0, 7)}
        </span>
      )}
      {op.git_branch && (
        <span className="flex items-center gap-1 font-mono">
          <GitBranch className="h-3 w-3 shrink-0" />
          {op.git_branch}
        </span>
      )}
      {op.git_repo && (
        <span className="flex items-center gap-1 font-mono">
          <Package className="h-3 w-3 shrink-0" />
          {op.git_repo}
        </span>
      )}
    </div>
  )
}

function StandardMeta({ op }: { op: OperationInfo }) {
  const hasAny = op.message_role
    || (op.total_tokens != null && op.total_tokens > 0)
    || op.duration_seconds != null
  if (!hasAny) return null

  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--color-text-secondary)]">
      {op.message_role && (
        <span className="flex items-center gap-1">
          <MessageSquare className="h-3 w-3" />
          {op.message_role}
        </span>
      )}
      {op.total_tokens != null && op.total_tokens > 0 && (
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

export function OperationMetaBadges({ op }: { op: OperationInfo }) {
  const isGitOp = op.operation_type.startsWith('git_')

  return (
    <>
      {isGitOp ? <GitOperationMeta op={op} /> : <StandardMeta op={op} />}
    </>
  )
}
