import { Check, Copy } from 'lucide-react'
import { useCopyFeedback } from '../../hooks/useCopyFeedback'
import './provenance.css'

/** Past either limit a task starts collapsed, so it does not push the page down. */
const COLLAPSE_LINES = 12
const COLLAPSE_CHARS = 800

function isLongTask(task: string): boolean {
  return task.length > COLLAPSE_CHARS || task.split('\n').length > COLLAPSE_LINES
}

/**
 * The task an execution was dispatched with, verbatim (#1307, #1030, #759).
 *
 * Rendered in a `<pre>` so whitespace survives: a prompt's indentation and
 * blank lines are part of what the agent was given. `null` is its own answer
 * - dispatched with no task - and is said, not hidden.
 */
export function DispatchedTask({ task }: { task: string | null | undefined }) {
  const { lastCopied, copy } = useCopyFeedback<'task'>()
  if (task == null) {
    return (
      <section className="provenance-card" aria-label="Dispatched task">
        <h3 className="provenance-card__title">Task</h3>
        <p className="provenance-muted">No task was recorded for this run.</p>
      </section>
    )
  }
  return (
    <section className="provenance-card" aria-label="Dispatched task">
      <details className="provenance-task" open={!isLongTask(task)}>
        <summary className="provenance-card__title">
          Task
          <span className="provenance-muted">
            {task.split('\n').length} lines &middot; {task.length.toLocaleString()} chars
          </span>
        </summary>
        <pre className="provenance-task__text" data-testid="dispatched-task-text">{task}</pre>
      </details>
      <button
        type="button"
        className="provenance-copy"
        onClick={() => void copy('task', task)}
        aria-label="Copy task"
      >
        {lastCopied === 'task' ? <Check size={14} /> : <Copy size={14} />}
        {lastCopied === 'task' ? 'Copied' : 'Copy'}
      </button>
    </section>
  )
}
