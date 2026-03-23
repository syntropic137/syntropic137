import { Activity } from 'lucide-react'
import { forwardRef } from 'react'
import { Card, CardContent, CardHeader } from '../../components'
import type { OperationInfo } from '../../types'
import { OperationTimelineItem } from './OperationTimelineItem'

interface OperationTimelineProps {
  operations: OperationInfo[]
}

export const OperationTimeline = forwardRef<HTMLDivElement, OperationTimelineProps>(
  function OperationTimeline({ operations }, ref) {
    return (
      <Card>
        <CardHeader
          title="Operations Timeline"
          subtitle={`${operations.length} operations recorded`}
        />
        <CardContent noPadding>
          {operations.length === 0 ? (
            <div className="p-8 text-center">
              <Activity className="mx-auto h-8 w-8 text-[var(--color-text-muted)]" />
              <p className="mt-2 text-sm text-[var(--color-text-muted)]">
                No operations recorded yet
              </p>
            </div>
          ) : (
            <div ref={ref} className="relative">
              <div className="absolute left-8 top-0 bottom-0 w-px bg-[var(--color-border)]" />
              <div className="space-y-0">
                {[...operations].reverse().map((op, idx) => (
                  <OperationTimelineItem key={op.operation_id} op={op} index={idx} />
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    )
  },
)
