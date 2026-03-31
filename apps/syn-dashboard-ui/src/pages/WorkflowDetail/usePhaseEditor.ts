import { useCallback, useEffect, useRef, useState } from 'react'

import { updatePhasePrompt } from '../../api/workflows'
import type { PhaseDefinition } from '../../types'

type EditorTab = 'write' | 'preview'

interface PhaseEditorState {
  isEditing: boolean
  editedPrompt: string
  editedModel: string
  editedTimeout: string
  editedTools: string
  activeTab: EditorTab
  isSaving: boolean
  error: string | null
  saveSuccess: boolean
}

export function usePhaseEditor(phase: PhaseDefinition, workflowId: string, onSaved?: () => void) {
  const [state, setState] = useState<PhaseEditorState>({
    isEditing: false,
    editedPrompt: phase.prompt_template ?? '',
    editedModel: phase.model ?? '',
    editedTimeout: String(phase.timeout_seconds ?? ''),
    editedTools: (phase.allowed_tools ?? []).join(', '),
    activeTab: 'write',
    isSaving: false,
    error: null,
    saveSuccess: false,
  })
  const saveTimerRef = useRef<ReturnType<typeof setTimeout>>(null)

  useEffect(() => () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current) }, [])

  const startEditing = useCallback(() => {
    setState({
      isEditing: true, activeTab: 'write', isSaving: false, error: null, saveSuccess: false,
      editedPrompt: phase.prompt_template ?? '', editedModel: phase.model ?? '',
      editedTimeout: String(phase.timeout_seconds ?? ''), editedTools: (phase.allowed_tools ?? []).join(', '),
    })
  }, [phase])

  const cancelEditing = useCallback(() => {
    setState((s) => ({ ...s, isEditing: false, error: null }))
  }, [])

  const setField = useCallback(<K extends keyof PhaseEditorState>(key: K, value: PhaseEditorState[K]) => {
    setState((s) => ({ ...s, [key]: value }))
  }, [])

  const handleSave = useCallback(async () => {
    if (!state.editedPrompt.trim()) { setState((s) => ({ ...s, error: 'Prompt cannot be empty' })); return }
    setState((s) => ({ ...s, isSaving: true, error: null }))
    try {
      const toolsList = state.editedTools.split(',').map((t) => t.trim()).filter(Boolean)
      await updatePhasePrompt(workflowId, phase.phase_id, {
        prompt_template: state.editedPrompt,
        model: state.editedModel || null,
        timeout_seconds: state.editedTimeout ? Number(state.editedTimeout) : null,
        allowed_tools: toolsList,
      })
      setState((s) => ({ ...s, isEditing: false, isSaving: false, saveSuccess: true }))
      saveTimerRef.current = setTimeout(() => setState((s) => ({ ...s, saveSuccess: false })), 2000)
      onSaved?.()
    } catch (err) {
      setState((s) => ({ ...s, isSaving: false, error: err instanceof Error ? err.message : 'Failed to save' }))
    }
  }, [state.editedPrompt, state.editedModel, state.editedTimeout, state.editedTools, workflowId, phase.phase_id, onSaved])

  return { ...state, startEditing, cancelEditing, setField, handleSave }
}
