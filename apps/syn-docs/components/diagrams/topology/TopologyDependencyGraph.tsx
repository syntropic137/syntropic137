'use client';

// Source: APS VIZ01 substandard - https://github.com/AgentParadise/agent-paradise-standards-system
// This is a local copy of the VIZ01-dashboard TopologyDependencyGraph component.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from 'd3-force';
import type { DependencyEdge, ModuleMetric, TopoNode } from './shared/types';
import { buildTopologyGraph, type FilterOptions } from './shared/filters';

interface SimNode extends SimulationNodeDatum, TopoNode {}
interface SimLink extends SimulationLinkDatum<SimNode> {
  weight: number;
}

export interface TopologyDependencyGraphProps {
  dependencies: DependencyEdge[];
  modules: ModuleMetric[];
  height?: number;
  className?: string;
  filterOptions?: FilterOptions;
}

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

function nodeRadius(loc: number): number {
  return clamp(Math.sqrt(loc) * 0.35, 4, 28);
}

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

export function TopologyDependencyGraph({
  dependencies,
  modules,
  height = 600,
  className,
  filterOptions,
}: TopologyDependencyGraphProps) {
  const { nodes, links } = useMemo(
    () => buildTopologyGraph(modules, dependencies, filterOptions),
    [modules, dependencies, filterOptions],
  );

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    node: TopoNode;
  } | null>(null);

  const simNodesRef = useRef<SimNode[]>([]);
  const simLinksRef = useRef<SimLink[]>([]);
  const transformRef = useRef({ x: 0, y: 0, k: 1 });
  const dragRef = useRef<{ active: boolean; lastX: number; lastY: number }>({
    active: false,
    lastX: 0,
    lastY: 0,
  });

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const { width, height: h } = canvas;
    const { x: tx, y: ty, k } = transformRef.current;

    ctx.clearRect(0, 0, width, h);
    ctx.save();
    ctx.translate(tx + width / 2, ty + h / 2);
    ctx.scale(k, k);

    for (const l of simLinksRef.current) {
      const s = l.source as SimNode;
      const t = l.target as SimNode;
      if (s.x == null || t.x == null) continue;
      ctx.beginPath();
      ctx.moveTo(s.x, s.y!);
      ctx.lineTo(t.x, t.y!);
      ctx.strokeStyle = `rgba(255,255,255,${clamp(l.weight * 0.15, 0.03, 0.25)})`;
      ctx.lineWidth = 0.5;
      ctx.stroke();
    }

    for (const n of simNodesRef.current) {
      if (n.x == null) continue;
      const r = nodeRadius(n.loc);
      ctx.beginPath();
      ctx.arc(n.x, n.y!, r, 0, Math.PI * 2);
      ctx.fillStyle = n.color;
      ctx.globalAlpha = 0.85;
      ctx.fill();
      ctx.globalAlpha = 1;
    }

    ctx.restore();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || nodes.length === 0) return;

    const simNodes: SimNode[] = nodes.map((n) => ({ ...n }));
    const simLinks: SimLink[] = links.map((l) => ({
      source: l.source,
      target: l.target,
      weight: l.weight,
    }));
    simNodesRef.current = simNodes;
    simLinksRef.current = simLinks as SimLink[];

    const sim = forceSimulation<SimNode>(simNodes)
      .force(
        'link',
        forceLink<SimNode, SimLink>(simLinks)
          .id((d) => d.id)
          .distance(80)
          .strength((l) => clamp(l.weight * 0.1, 0.01, 0.3)),
      )
      .force('charge', forceManyBody().strength(-60))
      .force('center', forceCenter(0, 0))
      .force('collide', forceCollide<SimNode>((d) => nodeRadius(d.loc) + 2))
      .alphaDecay(0.02)
      .on('tick', draw);

    return () => { sim.stop(); };
  }, [nodes, links, draw]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => {
      const parent = canvas.parentElement!;
      canvas.width = parent.clientWidth;
      canvas.height = parent.clientHeight;
      draw();
    });
    ro.observe(canvas.parentElement!);
    const parent = canvas.parentElement!;
    canvas.width = parent.clientWidth;
    canvas.height = parent.clientHeight;
    return () => ro.disconnect();
  }, [draw]);

  const screenToWorld = useCallback((sx: number, sy: number) => {
    const canvas = canvasRef.current!;
    const { x: tx, y: ty, k } = transformRef.current;
    return {
      wx: (sx - tx - canvas.width / 2) / k,
      wy: (sy - ty - canvas.height / 2) / k,
    };
  }, []);

  const hitTest = useCallback(
    (sx: number, sy: number): SimNode | null => {
      const { wx, wy } = screenToWorld(sx, sy);
      for (const n of simNodesRef.current) {
        if (n.x == null) continue;
        const r = nodeRadius(n.loc);
        const dx = n.x - wx;
        const dy = n.y! - wy;
        if (dx * dx + dy * dy <= r * r) return n;
      }
      return null;
    },
    [screenToWorld],
  );

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const factor = e.deltaY > 0 ? 0.9 : 1.1;
      transformRef.current.k = clamp(transformRef.current.k * factor, 0.1, 8);
      draw();
    },
    [draw],
  );

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    dragRef.current = { active: true, lastX: e.clientX, lastY: e.clientY };
  }, []);

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      const canvas = canvasRef.current!;
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;

      if (dragRef.current.active) {
        transformRef.current.x += e.clientX - dragRef.current.lastX;
        transformRef.current.y += e.clientY - dragRef.current.lastY;
        dragRef.current.lastX = e.clientX;
        dragRef.current.lastY = e.clientY;
        setTooltip(null);
        draw();
        return;
      }

      const hit = hitTest(sx, sy);
      if (hit) {
        setTooltip({ x: e.clientX, y: e.clientY, node: hit });
      } else {
        setTooltip(null);
      }
    },
    [draw, hitTest],
  );

  const onPointerUp = useCallback(() => {
    dragRef.current.active = false;
  }, []);

  return (
    <div className={className} style={{ position: 'relative', width: '100%', height }}>
      <canvas
        ref={canvasRef}
        style={{ width: '100%', height: '100%', cursor: 'grab', display: 'block' }}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      />

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

      {tooltip && (
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
      )}
    </div>
  );
}
