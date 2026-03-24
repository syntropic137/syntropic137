import {
  Activity,
  ExternalLink,
  GitBranch,
  Zap,
} from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  Breadcrumbs,
  Card,
  EmptyState,
  MetricCard,
  PageLoader,
} from '../components'
import { useTriggerData } from '../hooks/useTriggerData'
import { TriggerConfiguration } from './TriggerDetail/TriggerConfiguration'
import { TriggerFiringHistory } from './TriggerDetail/TriggerFiringHistory'
import { TriggerDetailHeader } from './TriggerDetail/TriggerDetailHeader'

export function TriggerDetail() {
  const { triggerId } = useParams<{ triggerId: string }>()
  const navigate = useNavigate()
  const { trigger, history, loading, error } = useTriggerData(triggerId)

  if (loading) return <PageLoader />

  if (error || !trigger) {
    return (
      <Card>
        <EmptyState
          icon={Zap}
          title="Trigger not found"
          description={error || `Could not find trigger with ID: ${triggerId}`}
          action={{ label: 'Back to Triggers', onClick: () => navigate('/triggers') }}
        />
      </Card>
    )
  }

  return (
    <div className="space-y-6">
      <Breadcrumbs
        items={[
          { label: 'Triggers', href: '/triggers' },
          { label: trigger.name },
        ]}
      />

      <TriggerDetailHeader trigger={trigger} />

      {/* Metrics */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard title="Fire Count" value={trigger.fire_count} icon={Activity} color="accent" />
        <MetricCard title="Event Type" value={trigger.event} icon={Zap} />
        <MetricCard title="Repository" value={trigger.repository || '\u2014'} icon={GitBranch} />
        <MetricCard
          title="Workflow"
          value={trigger.workflow_id.slice(0, 12) + '...'}
          icon={ExternalLink}
          href={`/workflows/${trigger.workflow_id}`}
          subtitle="View workflow \u2192"
        />
      </div>

      <TriggerConfiguration trigger={trigger} />
      <TriggerFiringHistory history={history} />
    </div>
  )
}
