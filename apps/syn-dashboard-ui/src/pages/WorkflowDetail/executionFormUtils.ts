import { useEffect } from 'react'
import type { InputDeclaration, PhaseDefinition } from '../../types'

/**
 * The input name the Task box supplies. The API merges the top-level `task`
 * field into `inputs` as `inputs["task"]`, so `$ARGUMENTS` and `{{task}}` are
 * two spellings of one value (docs/api/v1/workflows.md "Prompt Substitution").
 */
const TASK_INPUT_NAME = 'task'

/**
 * Whether the task typed into this form will reach the agent, and if not, what
 * to tell the operator. Callers render `message` and block submission on
 * `discarded`; they do not need to know which spelling a prompt used or that a
 * declared default counts as supplying a value.
 *
 * `discarded` blocks because the task is the whole instruction: the execution
 * would run the workflow's own fixed prompt, cost full money, and report
 * success for work nobody asked for (#1280). `empty` only warns, because
 * `$ARGUMENTS` as an optional addendum to a self-contained prompt is a
 * legitimate template. The `syn workflow run` CLI makes the same two calls for
 * the same reasons.
 */
export type TaskDeliverability =
  | { kind: 'ok' }
  | { kind: 'discarded'; message: string }
  | { kind: 'empty'; message: string }

export function assessTaskDeliverability(
  phases: PhaseDefinition[],
  declarations: InputDeclaration[],
  taskInput: string,
): TaskDeliverability {
  const consumed = phases.some((p) => {
    const template = p.prompt_template ?? ''
    return template.includes('$ARGUMENTS') || template.includes(`{{${TASK_INPUT_NAME}}}`)
  })

  if (taskInput && !consumed) {
    return {
      kind: 'discarded',
      message:
        'No phase prompt in this workflow consumes the task ($ARGUMENTS or {{task}}), ' +
        'so it would be discarded and the workflow would run its own prompt instead. ' +
        'Clear the Task box to run it as written.',
    }
  }

  const hasDeclaredDefault = declarations.some(
    (d) => d.name === TASK_INPUT_NAME && d.default != null,
  )
  if (consumed && !taskInput && !hasDeclaredDefault) {
    return {
      kind: 'empty',
      message: 'A phase prompt consumes the task, but none was entered — it will render empty.',
    }
  }

  return { kind: 'ok' }
}

export function canSubmitForm(
  declarations: InputDeclaration[],
  taskInput: string,
  formInputs: Record<string, string>,
): boolean {
  const hasMissingRequired = declarations.some(
    (d) => d.required && d.name !== 'task' && !formInputs[d.name]
  )
  if (hasMissingRequired) return false
  const taskRequired = declarations.some((d) => d.name === 'task' && d.required)
  if (taskRequired && !taskInput) return false
  return true
}

export function useFormDefaults(
  declarations: InputDeclaration[],
  setFormInputs: React.Dispatch<React.SetStateAction<Record<string, string>>>,
) {
  useEffect(() => {
    setFormInputs(prev => {
      const merged = { ...prev }
      for (const decl of declarations) {
        if (decl.default && decl.name !== 'task' && !merged[decl.name]) {
          merged[decl.name] = decl.default
        }
      }
      return merged
    })
  }, [declarations, setFormInputs])
}
