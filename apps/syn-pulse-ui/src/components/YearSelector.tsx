interface YearSelectorProps {
  labels: string[]
  selectedIndex: number
  onSelect: (index: number) => void
}

export function YearSelector({ labels, selectedIndex, onSelect }: YearSelectorProps) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, paddingTop: 20, paddingRight: 12, flexShrink: 0 }}>
      {labels.map((label, i) => (
        <button
          key={label}
          onClick={() => onSelect(i)}
          style={{
            padding: '4px 10px',
            borderRadius: 6,
            fontSize: 12,
            fontWeight: selectedIndex === i ? 600 : 400,
            color: selectedIndex === i ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
            background: selectedIndex === i ? 'var(--color-surface-elevated)' : 'transparent',
            border: 'none',
            cursor: 'pointer',
            textAlign: 'left',
            whiteSpace: 'nowrap',
            transition: 'all 0.15s',
          }}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
