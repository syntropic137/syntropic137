import { clsx } from 'clsx'
import { Play } from 'lucide-react'
import { useState } from 'react'

import type { InputDeclaration } from '../../types'
import { canSubmitForm, useFormDefaults } from './executionFormUtils'
import { FormInputField } from './FormInputField'
import { useExecutionSubmit } from './useExecutionSubmit'

interface WorkflowExecutionFormProps {
  workflowId: string
  declarations: InputDeclaration[]
  onExecutionStarted?: () => void
}

function SubmitButton({ disabled, isExecuting }: { disabled: boolean; isExecuting: boolean }) {
  return (
    <button
      type="submit"
      disabled={disabled}
      className={clsx(
        'inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all',
        disabled
          ? 'bg-slate-600 text-slate-300 cursor-not-allowed'
          : 'bg-gradient-to-r from-emerald-500 to-teal-500 text-white hover:from-emerald-600 hover:to-teal-600 shadow-lg shadow-emerald-500/25 hover:shadow-emerald-500/40'
      )}
    >
      <Play className={clsx('h-4 w-4', isExecuting && 'animate-pulse')} />
      {isExecuting ? 'Running...' : 'Run Workflow'}
    </button>
  )
}

function ExecutionMessage({ message }: { message: string | null }) {
  if (!message) return null
  const isError = message.startsWith('Error')
  return (
    <span className={clsx('text-xs', isError ? 'text-red-400' : 'text-emerald-400')}>
      {message}
    </span>
  )
}

export function WorkflowExecutionForm({ workflowId, declarations, onExecutionStarted }: WorkflowExecutionFormProps) {
  const [taskInput, setTaskInput] = useState('')
  const [formInputs, setFormInputs] = useState<Record<string, string>>({})
  const { isExecuting, executionMessage, handleSubmit } = useExecutionSubmit(onExecutionStarted)

  useFormDefaults(declarations, setFormInputs)

  const canExecute = canSubmitForm(declarations, taskInput, formInputs)
  const taskRequired = declarations.some((d) => d.name === 'task' && d.required)
  const extraDeclarations = declarations.filter(d => d.name !== 'task')
  const disabled = isExecuting || !canExecute

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!workflowId || disabled) return
    await handleSubmit(workflowId, formInputs, taskInput)
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col items-end gap-3 min-w-[320px]">
      <div className="w-full">
        <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">
          Task {taskRequired && <span className="text-red-400">*</span>}
        </label>
        <textarea
          value={taskInput}
          onChange={(e) => setTaskInput(e.target.value)}
          placeholder="Describe what to work on..."
          rows={2}
          className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </div>

      {extraDeclarations.map((decl) => (
        <FormInputField
          key={decl.name}
          decl={decl}
          value={formInputs[decl.name] ?? ''}
          onChange={(val) => setFormInputs(prev => ({ ...prev, [decl.name]: val }))}
        />
      ))}

      <SubmitButton disabled={disabled} isExecuting={isExecuting} />
      <ExecutionMessage message={executionMessage} />
    </form>
  )
}
