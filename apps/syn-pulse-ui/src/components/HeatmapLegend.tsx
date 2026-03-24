const LEGEND_COLORS = ['#1a1a2e', '#1a3366', '#2952a3', '#3d6dd9', '#4D80FF']

export function HeatmapLegend() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6, marginTop: 8, fontSize: 11, color: 'var(--color-text-muted)' }}>
      <span>Less</span>
      {LEGEND_COLORS.map((c) => (
        <div
          key={c}
          style={{
            width: 12,
            height: 12,
            borderRadius: 2,
            background: c,
            border: '1px solid rgba(255,255,255,0.05)',
          }}
        />
      ))}
      <span>More</span>
    </div>
  )
}
