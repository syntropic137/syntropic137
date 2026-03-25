import { useEffect, useRef, useState } from 'react'
import { executeWorkflow } from '../../api/workflows'

interface UseExecutionSubmitResult {
  isExecuting: boolean
  executionMessage: string | null
  handleSubmit: (workflowId: string, formInputs: Record<string, string>, taskInput: string) => Promise<void>
}

function formatSuccessMessage(executionId: string): string {
  return `Started! Execution ID: ${executionId.slice(0, 8)}...`
}

function formatErrorMessage(err: unknown): string {
  return `Error: ${err instanceof Error ? err.message : 'Failed to start'}`
}

function clearPendingTimeout(ref: React.MutableRefObject<ReturnType<typeof setTimeout> | null>): void {
  if (ref.current !== null) clearTimeout(ref.current)
}

export function useExecutionSubmit(onExecutionStarted?: () => void): UseExecutionSubmitResult {
  const [isExecuting, setIsExecuting] = useState(false)
  const [executionMessage, setExecutionMessage] = useState<string | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => clearPendingTimeout(timeoutRef)
  }, [])

  const handleSubmit = async (workflowId: string, formInputs: Record<string, string>, taskInput: string) => {
    setIsExecuting(true)
    setExecutionMessage(null)
    try {
      const response = await executeWorkflow(workflowId, { inputs: formInputs, task: taskInput || undefined, provider: 'claude' })
      setExecutionMessage(formatSuccessMessage(response.execution_id))
      onExecutionStarted?.()
      clearPendingTimeout(timeoutRef)
      timeoutRef.current = setTimeout(() => setExecutionMessage(null), 5000)
    } catch (err) {
      setExecutionMessage(formatErrorMessage(err))
    } finally {
      setIsExecuting(false)
    }
  }

  return { isExecuting, executionMessage, handleSubmit }
}
