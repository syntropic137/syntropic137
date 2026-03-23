const LEGEND_ITEMS: ReadonlyArray<readonly [string, string]> = [
  ['Orchestration / Workflow', '#4D80FF'],
  ['Session / Observability', '#1A80B3'],
  ['GitHub', '#8C50DC'],
  ['Artifact', '#22cc88'],
  ['Agentic Primitives', '#ff8844'],
  ['Event Sourcing Platform', '#44aaff'],
  ['Cost / Token', '#ffcc44'],
  ['Other', '#555'],
];

export function TopologyLegend() {
  return (
    <div
      style={{
        position: 'absolute',
        top: 12,
        right: 12,
        background: 'rgba(0,0,0,0.75)',
        borderRadius: 8,
        padding: '8px 12px',
        fontSize: 12,
        color: '#ccc',
        pointerEvents: 'none',
      }}
    >
      {LEGEND_ITEMS.map(([label, color]) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: color, flexShrink: 0 }} />
          {label}
        </div>
      ))}
      <div style={{ marginTop: 6, fontSize: 11, color: '#999' }}>
        Node size = lines of code · Scroll to zoom · Drag to pan
      </div>
    </div>
  );
}
