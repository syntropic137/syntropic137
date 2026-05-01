import { Activity, XCircle } from 'lucide-react'
import { useLayoutEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'

import { Breadcrumbs, Card, CardContent, CardHeader, EmptyState, PageLoader, SubagentList } from '../../components'
import type { BreadcrumbItem } from '../../components/Breadcrumbs'
import type { SessionResponse } from '../../types'
import { useSessionData } from '../../hooks'
import { ConversationLogViewer } from './ConversationLogViewer'
import { OperationTimeline } from './OperationTimeline'
import { SessionHeader } from './SessionHeader'
import { SessionMetrics } from './SessionMetrics'

function buildSessionBreadcrumbs(session: SessionResponse): BreadcrumbItem[] {
  const items: BreadcrumbItem[] = []
  if (session.workflow_id) {
    items.push({
      label: session.workflow_name || session.workflow_id,
      href: `/workflows/${session.workflow_id}`,
    })
  }
  if (session.execution_id) {
    items.push({ label: 'Execution', href: `/executions/${session.execution_id}` })
  }
  items.push({ label: session.phase_id || `Session ${session.id.slice(0, 8)}` })
  return items
}

function SessionErrorCard({ message }: { message: string }) {
  return (
    <Card className="border-red-500/30 bg-red-500/5">
      <CardContent className="flex items-start gap-3">
        <XCircle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-medium text-red-400">Execution Error</p>
          <p className="mt-1 text-sm text-[var(--color-text-secondary)]">{message}</p>
        </div>
      </CardContent>
    </Card>
  )
}

function useScrollAnchor(dependency: number | undefined) {
  const timelineRef = useRef<HTMLDivElement>(null)
  const prevScrollHeightRef = useRef(0)

  useLayoutEffect(() => {
    const el = timelineRef.current
    if (!el) return
    const prevHeight = prevScrollHeightRef.current
    const currentHeight = el.scrollHeight
    prevScrollHeightRef.current = currentHeight
    const heightDiff = currentHeight - prevHeight
    const shouldScroll = prevHeight > 0 && heightDiff > 0 && window.scrollY > 50
    if (shouldScroll) {
      window.scrollBy({ top: heightDiff, behavior: 'auto' })
    }
  }, [dependency])

  return timelineRef
}

function SubagentsSection({ subagents }: { subagents: SessionResponse['subagents'] }) {
  const list = subagents ?? []
  if (list.length === 0) return null
  return (
    <Card>
      <CardHeader
        title="Subagents"
        subtitle={`${list.length} subagents spawned via Task tool`}
      />
      <CardContent>
        <SubagentList subagents={list} title="" />
      </CardContent>
    </Card>
  )
}

export function SessionDetail() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const { session, loading, error, now, showConversationLog, setShowConversationLog } =
    useSessionData(sessionId)
  const timelineRef = useScrollAnchor(session?.operations?.length)

  if (loading) return <PageLoader />

  if (error || !session) {
    return (
      <Card>
        <EmptyState
          icon={Activity}
          title="Session not found"
          description={error || `Could not find session with ID: ${sessionId}`}
        />
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      {showConversationLog && sessionId && (
        <ConversationLogViewer sessionId={sessionId} onClose={() => setShowConversationLog(false)} />
      )}

      <Breadcrumbs items={buildSessionBreadcrumbs(session)} />
      <SessionHeader session={session} onViewConversationLog={() => setShowConversationLog(true)} />
      <SessionMetrics session={session} now={now} />

      {session.error_message && <SessionErrorCard message={session.error_message} />}

      <SubagentsSection subagents={session.subagents} />

      <section id="operations-timeline">
        <OperationTimeline ref={timelineRef} operations={session.operations} />
      </section>
    </div>
  )
}
