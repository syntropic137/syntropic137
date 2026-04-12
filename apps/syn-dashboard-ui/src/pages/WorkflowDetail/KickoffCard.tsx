import { Terminal } from 'lucide-react'

import { Card, CardContent, CardHeader } from '../../components'
import type { InputDeclaration } from '../../types'
import { WorkflowExecutionForm } from './WorkflowExecutionForm'

interface KickoffCardProps {
  workflowId: string
  declarations: InputDeclaration[]
  onExecutionStarted?: () => void
}

export function KickoffCard({ workflowId, declarations, onExecutionStarted }: KickoffCardProps) {
  return (
    <Card>
      <CardHeader title="Kickoff Execution" subtitle="Start a new workflow run" />
      <CardContent>
        <div className="mb-4 flex items-start gap-3 rounded-lg border border-blue-500/20 bg-blue-500/10 px-4 py-3">
          <Terminal className="h-4 w-4 shrink-0 text-blue-400 mt-0.5" />
          <p className="text-sm text-blue-300">
            This kickoff is intended to be run through{' '}
            <a
              href="https://www.npmjs.com/package/@syntropic137/cli"
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-blue-400 hover:text-blue-300 underline underline-offset-2"
            >@syntropic137/cli</a>{' '}
            via an orchestrator agent.
            Manual kickoff is available here as a convenience.
          </p>
        </div>
        <WorkflowExecutionForm
          workflowId={workflowId}
          declarations={declarations}
          onExecutionStarted={onExecutionStarted}
          layout="stacked"
        />
      </CardContent>
    </Card>
  )
}
