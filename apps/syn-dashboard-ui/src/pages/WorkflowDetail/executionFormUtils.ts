import { useEffect } from 'react'
import type { InputDeclaration } from '../../types'

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
