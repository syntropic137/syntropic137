import { Card, CardContent, CardHeader } from '../../components'
import type { TriggerDetail } from '../../api/triggers'

function JsonBlock({ data }: { data: Record<string, unknown> | null }) {
  if (!data || Object.keys(data).length === 0) {
    return <span className="text-sm text-[var(--color-text-muted)]">None</span>
  }
  return (
    <pre className="overflow-x-auto rounded-md bg-[var(--color-surface-elevated)] p-3 text-xs text-[var(--color-text-secondary)]">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

function ConfigSection({ label, data }: { label: string; data: Record<string, unknown> | null }) {
  return (
    <div>
      <h3 className="mb-1 text-xs font-medium uppercase tracking-wider text-[var(--color-text-secondary)]">
        {label}
      </h3>
      <JsonBlock data={data} />
    </div>
  )
}

export function TriggerConfiguration({ trigger }: { trigger: TriggerDetail }) {
  return (
    <Card>
      <CardHeader title="Configuration" subtitle="Trigger conditions, input mapping, and config" />
      <CardContent>
        <div className="space-y-4">
          <ConfigSection label="Conditions" data={trigger.conditions} />
          <ConfigSection label="Input Mapping" data={trigger.input_mapping} />
          <ConfigSection label="Config" data={trigger.config} />
        </div>
      </CardContent>
    </Card>
  )
}
