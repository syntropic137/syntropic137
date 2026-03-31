import { clsx } from 'clsx'
import { Check, Clock, Cpu, Pencil, Save, Wrench, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { updatePhasePrompt } from '../../api/workflows'
import { Card, CardContent, CardHeader } from '../../components'
import MarkdownViewer from '../../components/MarkdownViewer'
import type { PhaseDefinition } from '../../types'

interface PhasePromptEditorProps {
  phase: PhaseDefinition
  workflowId: string
  onSaved?: () => void
}

type EditorTab = 'write' | 'preview'

/**
 * Highlight prompt tokens ($ARGUMENTS, $TASK, {{variables}}) by wrapping
 * them in backtick code spans for the markdown renderer.
 * Skips tokens already inside code blocks or inline code.
 */
function highlightPromptTokens(content: string): string {
  const parts = content.split(/(```[\s\S]*?```|`[^`]+`)/)
  return parts
    .map((part, i) => {
      if (i % 2 === 1) return part
      return part
        .replace(/(\$ARGUMENTS|\$TASK)/g, '`$1`')
        .replace(/(\{\{[^}]+\}\})/g, '`$1`')
    })
    .join('')
}

function PhaseMetaBadges({ phase }: { phase: PhaseDefinition }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {phase.model && (
        <span className="inline-flex items-center gap-1 rounded-md bg-indigo-500/15 px-2 py-0.5 text-xs text-indigo-300 ring-1 ring-inset ring-indigo-500/25">
          <Cpu className="h-3 w-3" />
          {phase.model}
        </span>
      )}
      {phase.timeout_seconds > 0 && (
        <span className="inline-flex items-center gap-1 rounded-md bg-amber-500/15 px-2 py-0.5 text-xs text-amber-300 ring-1 ring-inset ring-amber-500/25">
          <Clock className="h-3 w-3" />
          {phase.timeout_seconds}s
        </span>
      )}
      {phase.allowed_tools?.length > 0 && (
        <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300 ring-1 ring-inset ring-emerald-500/25">
          <Wrench className="h-3 w-3" />
          {phase.allowed_tools.length} tools
        </span>
      )}
      {phase.argument_hint && (
        <span className="text-xs text-[var(--color-text-muted)]">
          {phase.argument_hint}
        </span>
      )}
    </div>
  )
}

function ConfigFields({
  model, timeout, tools,
  onModelChange, onTimeoutChange, onToolsChange,
}: {
  model: string; timeout: string; tools: string
  onModelChange: (v: string) => void; onTimeoutChange: (v: string) => void; onToolsChange: (v: string) => void
}) {
  const inputClass = 'w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1.5 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]'
  return (
    <div className="grid grid-cols-3 gap-3">
      <div>
        <label className="mb-1 block text-xs text-[var(--color-text-secondary)]">Model</label>
        <input type="text" value={model} onChange={(e) => onModelChange(e.target.value)} placeholder="e.g. sonnet, opus" className={inputClass} />
      </div>
      <div>
        <label className="mb-1 block text-xs text-[var(--color-text-secondary)]">Timeout (seconds)</label>
        <input type="number" value={timeout} onChange={(e) => onTimeoutChange(e.target.value)} placeholder="300" className={inputClass} />
      </div>
      <div>
        <label className="mb-1 block text-xs text-[var(--color-text-secondary)]">Allowed Tools</label>
        <input type="text" value={tools} onChange={(e) => onToolsChange(e.target.value)} placeholder="Bash, Read, Write" className={inputClass} />
      </div>
    </div>
  )
}

function TabBar({ activeTab, onTabChange }: { activeTab: EditorTab; onTabChange: (tab: EditorTab) => void }) {
  return (
    <div className="flex border-b border-[var(--color-border)]">
      {(['write', 'preview'] as const).map((tab) => (
        <button
          key={tab}
          onClick={() => onTabChange(tab)}
          className={clsx(
            'px-4 py-2 text-sm font-medium capitalize transition-colors',
            activeTab === tab
              ? 'border-b-2 border-[var(--color-accent)] text-[var(--color-text-primary)]'
              : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
          )}
        >
          {tab}
        </button>
      ))}
    </div>
  )
}

function PromptContent({ tab, prompt }: { tab: EditorTab; prompt: string; onPromptChange?: (v: string) => void }) {
  if (tab === 'preview') {
    return (
      <div className="min-h-[400px] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        {prompt ? <MarkdownViewer content={highlightPromptTokens(prompt)} /> : <p className="text-sm text-[var(--color-text-muted)] italic">Nothing to preview</p>}
      </div>
    )
  }
  return null
}

export function PhasePromptEditor({ phase, workflowId, onSaved }: PhasePromptEditorProps) {
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

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    }
  }, [])

  function startEditing() {
    setEditedPrompt(phase.prompt_template ?? '')
    setEditedModel(phase.model ?? '')
    setEditedTimeout(String(phase.timeout_seconds ?? ''))
    setEditedTools((phase.allowed_tools ?? []).join(', '))
    setActiveTab('write')
    setError(null)
    setSaveSuccess(false)
    setIsEditing(true)
  }

  async function handleSave() {
    if (!editedPrompt.trim()) { setError('Prompt cannot be empty'); return }
    setIsSaving(true)
    setError(null)
    try {
      const toolsList = editedTools.split(',').map((t) => t.trim()).filter(Boolean)
      await updatePhasePrompt(workflowId, phase.phase_id, {
        prompt_template: editedPrompt,
        model: editedModel || null,
        timeout_seconds: editedTimeout ? Number(editedTimeout) : null,
        allowed_tools: toolsList,
      })
      setIsEditing(false)
      setSaveSuccess(true)
      saveTimerRef.current = setTimeout(() => setSaveSuccess(false), 2000)
      onSaved?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setIsSaving(false)
    }
  }

  const hasPrompt = !!phase.prompt_template

  return (
    <Card>
      <CardHeader
        title={`Phase: ${phase.name}`}
        subtitle={phase.description ?? `Phase ${phase.order}`}
        action={!isEditing ? (
          <button onClick={startEditing} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-surface-elevated)] px-3 py-1.5 text-sm text-[var(--color-text-secondary)] ring-1 ring-inset ring-[var(--color-border)] transition-colors hover:text-[var(--color-text-primary)] hover:ring-[var(--color-accent)]">
            <Pencil className="h-3.5 w-3.5" />
            Edit
          </button>
        ) : undefined}
      />
      <CardContent>
        <PhaseMetaBadges phase={phase} />

        {isEditing ? (
          <div className="mt-4 space-y-4">
            <ConfigFields model={editedModel} timeout={editedTimeout} tools={editedTools} onModelChange={setEditedModel} onTimeoutChange={setEditedTimeout} onToolsChange={setEditedTools} />
            <TabBar activeTab={activeTab} onTabChange={setActiveTab} />
            {activeTab === 'write' ? (
              <textarea value={editedPrompt} onChange={(e) => setEditedPrompt(e.target.value)} className="min-h-[400px] w-full resize-y rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 font-mono text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none focus:ring-1 focus:ring-[var(--color-accent)]" placeholder="Enter prompt template..." />
            ) : (
              <PromptContent tab={activeTab} prompt={editedPrompt} />
            )}
            {error && <p className="text-sm text-[var(--color-error)]">{error}</p>}
            <div className="flex items-center gap-2">
              <button onClick={handleSave} disabled={isSaving || !editedPrompt.trim()} className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50">
                <Save className="h-4 w-4" />
                {isSaving ? 'Saving...' : 'Save'}
              </button>
              <button onClick={() => { setIsEditing(false); setError(null) }} disabled={isSaving} className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm text-[var(--color-text-secondary)] transition-colors hover:text-[var(--color-text-primary)]">
                <X className="h-4 w-4" />
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-4">
            {saveSuccess && (
              <div className="mb-3 inline-flex items-center gap-1.5 rounded-md bg-emerald-500/15 px-2.5 py-1 text-xs text-emerald-300 ring-1 ring-inset ring-emerald-500/25">
                <Check className="h-3 w-3" />
                Saved
              </div>
            )}
            {hasPrompt ? (
              <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
                <MarkdownViewer content={highlightPromptTokens(phase.prompt_template!)} />
              </div>
            ) : (
              <p className="text-sm text-[var(--color-text-muted)] italic">No prompt template defined for this phase.</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
