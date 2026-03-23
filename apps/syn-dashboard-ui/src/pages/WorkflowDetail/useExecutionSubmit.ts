import { useState } from 'react'
import { executeWorkflow } from '../../api/workflows'

interface UseExecutionSubmitResult {
  isExecuting: boolean
  executionMessage: string | null
  handleSubmit: (workflowId: string, formInputs: Record<string, string>, taskInput: string) => Promise<void>
}

export function useExecutionSubmit(onExecutionStarted?: () => void): UseExecutionSubmitResult {
  const [isExecuting, setIsExecuting] = useState(false)
  const [executionMessage, setExecutionMessage] = useState<string | null>(null)

  const handleSubmit = async (workflowId: string, formInputs: Record<string, string>, taskInput: string) => {
    setIsExecuting(true)
    setExecutionMessage(null)
    try {
      const response = await executeWorkflow(workflowId, { inputs: formInputs, task: taskInput || undefined, provider: 'claude' })
      setExecutionMessage(`Started! Execution ID: ${response.execution_id.slice(0, 8)}...`)
      onExecutionStarted?.()
      setTimeout(() => setExecutionMessage(null), 5000)
    } catch (err) {
      setExecutionMessage(`Error: ${err instanceof Error ? err.message : 'Failed to start'}`)
    } finally {
      setIsExecuting(false)
    }
  }

  return { isExecuting, executionMessage, handleSubmit }
}
