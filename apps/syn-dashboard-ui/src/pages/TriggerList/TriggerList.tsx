import { AlertCircle, Zap } from 'lucide-react'

import { EmptyState, PageLoader } from '../../components'
import { useTriggerActions } from '../../hooks/useTriggerActions'
import { useTriggerList } from '../../hooks/useTriggerList'
import { TriggerCard } from './TriggerCard'
import { TriggerFilters } from './TriggerFilters'

export function TriggerList() {
  const {
    setTriggers,
    filteredTriggers,
    loading,
    error,
    setError,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
    fetchTriggers,
  } = useTriggerList()

  const {
    handleToggle,
    handleDelete,
    busyIds,
    actionError,
    clearError,
  } = useTriggerActions(setTriggers, fetchTriggers)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">Triggers</h1>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
          GitHub webhook trigger rules that automatically start workflows
        </p>
      </div>

      {/* Error banner */}
      {(error || actionError) && (
        <div className="flex items-center gap-2 rounded-md border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error || actionError}</span>
          <button
            type="button"
            onClick={() => { setError(null); clearError() }}
            className="ml-auto text-xs hover:text-red-300"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Filters */}
      <TriggerFilters
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        statusFilter={statusFilter}
        onStatusChange={setStatusFilter}
      />

      {/* Content */}
      {loading ? (
        <PageLoader />
      ) : filteredTriggers.length === 0 ? (
        <EmptyState
          title="No triggers found"
          description="Create a trigger to automatically start workflows on GitHub events"
          icon={Zap}
        />
      ) : (
        <div className="space-y-2">
          {filteredTriggers.map((trigger) => (
            <TriggerCard
              key={trigger.trigger_id}
              trigger={trigger}
              isBusy={busyIds.has(trigger.trigger_id)}
              onToggle={handleToggle}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}
    </div>
  )
}
