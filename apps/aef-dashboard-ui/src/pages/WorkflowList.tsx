import { ChevronRight, GitBranch, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { listWorkflows } from '../api/client'
import { Card, CardContent, EmptyState, PageLoader, StatusBadge } from '../components'
import type { WorkflowSummary } from '../types'

export function WorkflowList() {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const pageSize = 20

  useEffect(() => {
    let cancelled = false
    listWorkflows({
      status: statusFilter || undefined,
      page,
      page_size: pageSize,
    })
      .then((data) => {
        if (cancelled) return
        setWorkflows(data.workflows)
        setTotal(data.total)
        setLoading(false)
      })
      .catch((err) => { if (!cancelled) { console.error(err); setLoading(false) } })
    return () => { cancelled = true }
  }, [statusFilter, page])

  const filteredWorkflows = searchQuery
    ? workflows.filter((w) =>
        w.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        w.id.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : workflows

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Workflows</h1>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
            Manage and monitor your agentic workflows
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-text-muted)]" />
          <input
            type="text"
            placeholder="Search workflows..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] py-2 pl-10 pr-4 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value)
            setPage(1)
          }}
          className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]"
        >
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="in_progress">In Progress</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>

      {/* Workflow list */}
      {loading ? (
        <PageLoader />
      ) : filteredWorkflows.length === 0 ? (
        <Card>
          <EmptyState
            icon={GitBranch}
            title={searchQuery ? 'No matching workflows' : 'No workflows yet'}
            description={
              searchQuery
                ? 'Try adjusting your search query'
                : 'Run your first workflow with `aef run workflow.yaml`'
            }
          />
        </Card>
      ) : (
        <>
          <div className="space-y-2">
            {filteredWorkflows.map((workflow, idx) => (
              <Link
                key={workflow.id}
                to={`/workflows/${workflow.id}`}
                className="block animate-fade-in"
                style={{ animationDelay: `${idx * 30}ms` }}
              >
                <Card hover>
                  <CardContent className="flex items-center justify-between py-3">
                    <div className="flex items-center gap-4">
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--color-surface-elevated)]">
                        <GitBranch className="h-5 w-5 text-[var(--color-accent)]" />
                      </div>
                      <div>
                        <div className="flex items-center gap-3">
                          <span className="font-medium text-[var(--color-text-primary)]">
                            {workflow.name}
                          </span>
                          <StatusBadge status={workflow.status} size="sm" />
                        </div>
                        <div className="mt-0.5 flex items-center gap-3 text-xs text-[var(--color-text-secondary)]">
                          <span className="font-mono">{workflow.id.slice(0, 8)}...</span>
                          <span>•</span>
                          <span>{workflow.workflow_type}</span>
                          <span>•</span>
                          <span>{workflow.phase_count} phases</span>
                        </div>
                      </div>
                    </div>
                    <ChevronRight className="h-5 w-5 text-[var(--color-text-muted)]" />
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-[var(--color-text-secondary)]">
                Showing {(page - 1) * pageSize + 1}-{Math.min(page * pageSize, total)} of {total}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-elevated)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Previous
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-elevated)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
