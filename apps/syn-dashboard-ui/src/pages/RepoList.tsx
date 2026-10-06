/**
 * Repos page — composition only.
 *
 * The connected repositories (registered, or reachable by the GitHub App),
 * which system owns each, and whether each is attached to a GitHub App
 * installation. Read-only: repos are registered from the CLI, not from here.
 *
 * No link to a repo's executions: `/executions` has no repository filter to
 * link to, and inventing one is a separate change.
 */

import { FolderGit2, Lock } from 'lucide-react'

import { Card, EmptyState, PageLoader } from '../components'
import { useRepoList, type Attachment, type RepoRow } from '../hooks/useRepoList'

const MUTED_BADGE =
  'rounded-full bg-[var(--color-surface-elevated)] px-2 py-0.5 text-xs text-[var(--color-text-muted)]'

function AttachedBadge({ attachment }: { attachment: Attachment }) {
  if (attachment === 'attached') {
    return (
      <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-400">
        Attached
      </span>
    )
  }
  return <span className={MUTED_BADGE}>{attachment === 'unknown' ? 'Unknown' : 'Not attached'}</span>
}

function RepoTable({ repos }: { repos: RepoRow[] }) {
  return (
    <Card>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
            <th className="px-4 py-2 font-medium">Repository</th>
            <th className="px-4 py-2 font-medium">System</th>
            <th className="px-4 py-2 font-medium">GitHub App</th>
          </tr>
        </thead>
        <tbody>
          {repos.map((repo) => (
            <tr key={repo.key} className="border-b border-[var(--color-border)] last:border-0">
              <td className="px-4 py-2 text-[var(--color-text-primary)]">
                <span className="inline-flex items-center gap-1.5">
                  {repo.fullName}
                  {repo.isPrivate && (
                    <Lock aria-label="Private" className="h-3 w-3 text-[var(--color-text-muted)]" />
                  )}
                </span>
              </td>
              <td className="px-4 py-2 text-[var(--color-text-secondary)]">
                {repo.system ??
                  (repo.registered ? (
                    <span className="text-[var(--color-text-muted)]">None</span>
                  ) : (
                    <span className={MUTED_BADGE} title="Reachable by the GitHub App; not registered with `syn repo register`">
                      Not registered
                    </span>
                  ))}
              </td>
              <td className="px-4 py-2">
                <AttachedBadge attachment={repo.attachment} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}

export function RepoList() {
  const state = useRepoList()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Repos</h1>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          Repositories registered with the platform or reachable by the GitHub App
          {state.kind === 'ready' && state.repos.length > 0 && (
            <span className="text-[var(--color-text-muted)]"> · {state.repos.length} connected</span>
          )}
        </p>
      </div>

      {state.kind === 'loading' ? (
        <PageLoader />
      ) : state.kind === 'error' ? (
        <Card>
          <EmptyState
            icon={FolderGit2}
            title="Could not load repositories"
            description={state.message}
          />
        </Card>
      ) : state.repos.length === 0 ? (
        <Card>
          <EmptyState
            icon={FolderGit2}
            title="No repositories connected"
            description="Register one with `syn repo register --url owner/repo`, then install the GitHub App on it so workflows can act on it."
          />
        </Card>
      ) : (
        <RepoTable repos={state.repos} />
      )}
    </div>
  )
}
