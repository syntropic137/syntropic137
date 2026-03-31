import { clsx } from 'clsx'
import { Check, Clock, Cpu, Pencil, Save, Wrench, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { updatePhasePrompt } from '../../api/workflows'
import { Card, CardContent, CardHeader } from '../../components'
import MarkdownViewer from '../../components/MarkdownViewer'
import type { PhaseDefinition } from '../../types'

type EditorTab = 'write' | 'preview'

/** Wrap prompt tokens in backtick code spans, skipping existing code blocks. */
function highlightPromptTokens(content: string): string {
  const parts = content.split(/(```[\s\S]*?```|`[^`]+`)/)
  return parts
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
      {phase.model && (
        <span className="inline-flex items-center gap-1 rounded-md bg-indigo-500/15 px-2 py-0.5 text-xs text-indigo-300 ring-1 ring-inset ring-indigo-500/25"><Cpu className="h-3 w-3" />{phase.model}</span>
      )}
      {phase.timeout_seconds > 0 && (
        <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-2 py-0.5 text-xs text-amber-300 ring-1 ring-inset ring-amber-500/25"><Clock className="h-3 w-3" />{phase.timeout_seconds}s</span>
      )}
      {phase.allowed_tools?.length > 0 && (
        <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300 ring-1 ring-inset ring-emerald-500/25"><Wrench className="h-3 w-3" />{phase.allowed_tools.length} tools</span>
      )}
      {phase.argument_hint && <span className="text-xs text-[var(--color-text-muted)]">{phase.argument_hint}</span>}
    </div>
  )
}

const inputClass = 'w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]'

function ConfigFields({ model, timeout, tools, onModelChange, onTimeoutChange, onToolsChange }: {
  model: string; timeout: string; tools: string
  onModelChange: (v: string) => void; onTimeoutChange: (v: string) => void; onToolsChange: (v: string) => void
}) {
  return (
    <div className="grid grid-cols-3 gap-3">
      <div><label className="mb-1 block text-xs text-[var(--color-text-secondary)]">Model</label><input type="text" value={model} onChange={(e) => onModelChange(e.target.value)} placeholder="e.g. sonnet, opus" className={inputClass} /></div>
      <div><label className="mb-1 block text-xs text-[var(--color-text-secondary)]">Timeout (seconds)</label><input type="number" value={timeout} onChange={(e) => onTimeoutChange(e.target.value)} placeholder="300" className={inputClass} /></div>
      <div><label className="mb-1 block text-xs text-[var(--color-text-secondary)]">Allowed Tools</label><input type="text" value={tools} onChange={(e) => onToolsChange(e.target.value)} placeholder="Bash, Read, Write" className={inputClass} /></div>
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

const textareaClass = 'min-h-[400px] w-full resize-y rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 font-mono text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]'

function PromptPreview({ content }: { content: string }) {
  return (
    <div className="min-h-[400px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      {content ? <MarkdownViewer content={highlightPromptTokens(content)} /> : <p className="text-sm text-[var(--color-text-muted)] italic">Nothing to preview</p>}
    </div>
  )
}

function EditorForm({ prompt, model, timeout, tools, activeTab, error, isSaving, onPromptChange, onModelChange, onTimeoutChange, onToolsChange, onTabChange, onSave, onCancel }: {
  prompt: string; model: string; timeout: string; tools: string; activeTab: EditorTab; error: string | null; isSaving: boolean
  onPromptChange: (v: string) => void; onModelChange: (v: string) => void; onTimeoutChange: (v: string) => void; onToolsChange: (v: string) => void
  onTabChange: (tab: EditorTab) => void; onSave: () => void; onCancel: () => void
}) {
  return (
    <div className="mt-4 space-y-4">
      <ConfigFields model={model} timeout={timeout} tools={tools} onModelChange={onModelChange} onTimeoutChange={onTimeoutChange} onToolsChange={onToolsChange} />
      <TabBar activeTab={activeTab} onTabChange={onTabChange} />
      {activeTab === 'write'
        ? <textarea value={prompt} onChange={(e) => onPromptChange(e.target.value)} className={textareaClass} placeholder="Enter prompt template..." />
        : <PromptPreview content={prompt} />}
      {error && <p className="text-sm text-[var(--color-error)]">{error}</p>}
      <div className="flex items-center gap-2">
        <button onClick={onSave} disabled={isSaving || !prompt.trim()} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"><Save className="h-4 w-4" />{isSaving ? 'Saving...' : 'Save'}</button>
        <button onClick={onCancel} disabled={isSaving} className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm text-[var(--color-text-secondary)] transition-colors hover:text-[var(--color-text-primary)]"><X className="h-4 w-4" />Cancel</button>
      </div>
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
  const [isEditing, setIsEditing] = useState(false)
  const [editedPrompt, setEditedPrompt] = useState(phase.prompt_template ?? '')
  const [editedModel, setEditedModel] = useState(phase.model ?? '')
  const [editedTimeout, setEditedTimeout] = useState(String(phase.timeout_seconds ?? ''))
  const [editedTools, setEditedTools] = useState((phase.allowed_tools ?? []).join(', '))
  const [activeTab, setActiveTab] = useState<EditorTab>('write')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout>>(null)

  useEffect(() => () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current) }, [])

  function startEditing() {
    setEditedPrompt(phase.prompt_template ?? ''); setEditedModel(phase.model ?? '')
    setEditedTimeout(String(phase.timeout_seconds ?? '')); setEditedTools((phase.allowed_tools ?? []).join(', '))
    setActiveTab('write'); setError(null); setSaveSuccess(false); setIsEditing(true)
  }

  async function handleSave() {
    if (!editedPrompt.trim()) { setError('Prompt cannot be empty'); return }
    setIsSaving(true); setError(null)
    try {
      const toolsList = editedTools.split(',').map((t) => t.trim()).filter(Boolean)
      await updatePhasePrompt(workflowId, phase.phase_id, { prompt_template: editedPrompt, model: editedModel || null, timeout_seconds: editedTimeout ? Number(editedTimeout) : null, allowed_tools: toolsList })
      setIsEditing(false); setSaveSuccess(true)
      saveTimerRef.current = setTimeout(() => setSaveSuccess(false), 2000)
      onSaved?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save')
    } finally { setIsSaving(false) }
  }

  return (
    <Card>
      <CardHeader title={`Phase: ${phase.name}`} subtitle={phase.description ?? `Phase ${phase.order}`}
        action={!isEditing ? <button onClick={startEditing} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-surface-elevated)] px-3 py-1.5 text-sm text-[var(--color-text-secondary)] ring-1 ring-inset ring-[var(--color-border)] transition-colors hover:text-[var(--color-text-primary)] hover:ring-[var(--color-accent)]"><Pencil className="h-3.5 w-3.5" />Edit</button> : undefined} />
      <CardContent>
        <PhaseMetaBadges phase={phase} />
        {isEditing
          ? <EditorForm prompt={editedPrompt} model={editedModel} timeout={editedTimeout} tools={editedTools} activeTab={activeTab} error={error} isSaving={isSaving} onPromptChange={setEditedPrompt} onModelChange={setEditedModel} onTimeoutChange={setEditedTimeout} onToolsChange={setEditedTools} onTabChange={setActiveTab} onSave={handleSave} onCancel={() => { setIsEditing(false); setError(null) }} />
          : <PromptViewer prompt={phase.prompt_template} saveSuccess={saveSuccess} />}
      </CardContent>
    </Card>
  )
}
