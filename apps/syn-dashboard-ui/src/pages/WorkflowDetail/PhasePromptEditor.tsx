import { clsx } from 'clsx'
import { Check, Clock, Cpu, Pencil, Save, Wrench, X } from 'lucide-react'

import { Card, CardContent, CardHeader } from '../../components'
import MarkdownViewer from '../../components/MarkdownViewer'
import type { PhaseDefinition } from '../../types'
import { usePhaseEditor } from './usePhaseEditor'

type EditorTab = 'write' | 'preview'

/** Wrap prompt tokens in backtick code spans, skipping existing code blocks. */
function highlightPromptTokens(content: string): string {
  return content
    .split(/(```[\s\S]*?```|`[^`]+`)/)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part.replace(/(\$ARGUMENTS|\$TASK)/g, '`$1`').replace(/(\{\{[^}]+\}\})/g, '`$1`')
    )
    .join('')
}

function PhaseMetaBadges({ phase }: { phase: PhaseDefinition }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {phase.model && <span className="inline-flex items-center gap-1 rounded-md bg-indigo-500/15 px-2 py-0.5 text-xs text-indigo-300 ring-1 ring-inset ring-indigo-500/25"><Cpu className="h-3 w-3" />{phase.model}</span>}
      {phase.timeout_seconds > 0 && <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-2 py-0.5 text-xs text-amber-300 ring-1 ring-inset ring-amber-500/25"><Clock className="h-3 w-3" />{phase.timeout_seconds}s</span>}
      {phase.allowed_tools?.length > 0 && <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300 ring-1 ring-inset ring-emerald-500/25"><Wrench className="h-3 w-3" />{phase.allowed_tools.length} tools</span>}
      {phase.argument_hint && <span className="text-xs text-[var(--color-text-muted)]">{phase.argument_hint}</span>}
    </div>
  )
}

const inputClass = 'w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]'
const textareaClass = 'min-h-[400px] w-full resize-y rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 font-mono text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]'

function ConfigFields({ model, timeout, tools, onChange }: {
  model: string; timeout: string; tools: string
  onChange: (field: string, value: string) => void
}) {
  return (
    <div className="grid grid-cols-3 gap-3">
      <div><label className="mb-1 block text-xs text-[var(--color-text-secondary)]">Model</label><input type="text" value={model} onChange={(e) => onChange('editedModel', e.target.value)} placeholder="e.g. sonnet, opus" className={inputClass} /></div>
      <div><label className="mb-1 block text-xs text-[var(--color-text-secondary)]">Timeout (seconds)</label><input type="number" value={timeout} onChange={(e) => onChange('editedTimeout', e.target.value)} placeholder="300" className={inputClass} /></div>
      <div><label className="mb-1 block text-xs text-[var(--color-text-secondary)]">Allowed Tools</label><input type="text" value={tools} onChange={(e) => onChange('editedTools', e.target.value)} placeholder="Bash, Read, Write" className={inputClass} /></div>
    </div>
  )
}

function TabBar({ activeTab, onTabChange }: { activeTab: EditorTab; onTabChange: (tab: EditorTab) => void }) {
  return (
    <div className="flex border-b border-[var(--color-border)]">
      {(['write', 'preview'] as const).map((tab) => (
        <button key={tab} onClick={() => onTabChange(tab)} className={clsx('px-4 py-2 text-sm font-medium capitalize transition-colors', activeTab === tab ? 'border-b-2 border-[var(--color-accent)] text-[var(--color-text-primary)]' : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]')}>{tab}</button>
      ))}
    </div>
  )
}

function PromptViewer({ prompt, saveSuccess }: { prompt: string | null; saveSuccess: boolean }) {
  return (
    <div className="mt-4">
      {saveSuccess && <div className="mb-3 inline-flex items-center gap-1.5 rounded-md bg-emerald-500/15 px-2.5 py-1 text-xs text-emerald-300 ring-1 ring-inset ring-emerald-500/25"><Check className="h-3 w-3" />Saved</div>}
      {prompt
        ? <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"><MarkdownViewer content={highlightPromptTokens(prompt)} /></div>
        : <p className="text-sm text-[var(--color-text-muted)] italic">No prompt template defined for this phase.</p>}
    </div>
  )
}

export function PhasePromptEditor({ phase, workflowId, onSaved }: { phase: PhaseDefinition; workflowId: string; onSaved?: () => void }) {
  const editor = usePhaseEditor(phase, workflowId, onSaved)

  return (
    <Card>
      <CardHeader title={`Phase: ${phase.name}`} subtitle={phase.description ?? `Phase ${phase.order}`}
        action={!editor.isEditing ? <button onClick={editor.startEditing} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-surface-elevated)] px-3 py-1.5 text-sm text-[var(--color-text-secondary)] ring-1 ring-inset ring-[var(--color-border)] transition-colors hover:text-[var(--color-text-primary)] hover:ring-[var(--color-accent)]"><Pencil className="h-3.5 w-3.5" />Edit</button> : undefined} />
      <CardContent>
        <PhaseMetaBadges phase={phase} />
        {editor.isEditing ? (
          <div className="mt-4 space-y-4">
            <ConfigFields model={editor.editedModel} timeout={editor.editedTimeout} tools={editor.editedTools} onChange={(f, v) => editor.setField(f as 'editedModel', v)} />
            <TabBar activeTab={editor.activeTab} onTabChange={(tab) => editor.setField('activeTab', tab)} />
            {editor.activeTab === 'write'
              ? <textarea value={editor.editedPrompt} onChange={(e) => editor.setField('editedPrompt', e.target.value)} className={textareaClass} placeholder="Enter prompt template..." />
              : <div className="min-h-[400px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">{editor.editedPrompt ? <MarkdownViewer content={highlightPromptTokens(editor.editedPrompt)} /> : <p className="text-sm text-[var(--color-text-muted)] italic">Nothing to preview</p>}</div>}
            {editor.error && <p className="text-sm text-[var(--color-error)]">{editor.error}</p>}
            <div className="flex items-center gap-2">
              <button onClick={editor.handleSave} disabled={editor.isSaving || !editor.editedPrompt.trim()} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"><Save className="h-4 w-4" />{editor.isSaving ? 'Saving...' : 'Save'}</button>
              <button onClick={editor.cancelEditing} disabled={editor.isSaving} className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm text-[var(--color-text-secondary)] transition-colors hover:text-[var(--color-text-primary)]"><X className="h-4 w-4" />Cancel</button>
            </div>
          </div>
        ) : <PromptViewer prompt={phase.prompt_template} saveSuccess={editor.saveSuccess} />}
      </CardContent>
    </Card>
  )
}
