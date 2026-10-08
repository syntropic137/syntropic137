import { Lock } from 'lucide-react'

import type { EvalSummary } from '../../api/evals'

function Baselines({ e }: { e: EvalSummary }) {
  return (
    <ul className="space-y-0.5 text-xs text-[var(--color-text-muted)]" aria-label="Baseline">
      {e.baseline_repos.map((repo) => (
        <li key={repo.repository} className="break-all">
          Baseline{' '}
          <a
            href={`https://github.com/${repo.repository}/tree/${repo.commit_sha}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[var(--color-accent)] hover:underline"
          >
            {repo.repository}@{repo.commit_sha.slice(0, 12)}
          </a>{' '}
          ({repo.requested_ref})
        </li>
      ))}
    </ul>
  )
}

/** What the eval asks: its name, goal, Baseline commit(s) and tags. */
export function EvalHeader({ e }: { e: EvalSummary }) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="min-w-0 break-words text-2xl font-bold text-[var(--color-text-primary)]">{e.name}</h1>
        {e.frozen && (
          <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/10 px-2 py-0.5 text-xs text-sky-400">
            <Lock className="h-3 w-3" /> Frozen
          </span>
        )}
      </div>
      <p className="whitespace-pre-wrap break-words text-sm text-[var(--color-text-secondary)]">{e.goal}</p>
      <Baselines e={e} />
      {e.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {e.tags.map((tag) => (
            <span key={tag} className="break-all rounded-full bg-[var(--color-accent)]/10 px-2 py-0.5 text-[11px] text-[var(--color-accent)]">
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
