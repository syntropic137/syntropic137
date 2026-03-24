import type { InputDeclaration } from '../../types'

export function FormInputField({ decl, value, onChange }: {
  decl: InputDeclaration
  value: string
  onChange: (value: string) => void
}) {
  return (
    <div className="w-full">
      <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">
        {decl.name} {decl.required && <span className="text-red-400">*</span>}
        {decl.description && (
          <span className="ml-1 font-normal text-[var(--color-text-muted)]">&mdash; {decl.description}</span>
        )}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={decl.default ?? ''}
        className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
      />
    </div>
  )
}
