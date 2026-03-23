import type { TopoNode } from './shared/types';

interface TopologyTooltipProps {
  tooltip: { x: number; y: number; node: TopoNode } | null;
}

export function TopologyTooltip({ tooltip }: TopologyTooltipProps) {
  if (!tooltip) return null;

  return (
    <div
      style={{
        position: 'fixed',
        left: tooltip.x + 14,
        top: tooltip.y - 10,
        background: 'rgba(0,0,0,0.9)',
        border: `1px solid ${tooltip.node.color}`,
        borderRadius: 6,
        padding: '8px 12px',
        fontSize: 12,
        color: '#eee',
        pointerEvents: 'none',
        zIndex: 100,
        maxWidth: 320,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 4, color: tooltip.node.color }}>
        {tooltip.node.name}
      </div>
      <div>LOC: {tooltip.node.loc}</div>
      <div>Functions: {tooltip.node.functionCount}</div>
      <div>Avg cyclomatic: {tooltip.node.avgCyclomatic.toFixed(1)}</div>
      <div>Instability: {tooltip.node.instability.toFixed(2)}</div>
      <div style={{ color: '#888', marginTop: 4, fontSize: 11 }}>{tooltip.node.id}</div>
    </div>
  );
}
