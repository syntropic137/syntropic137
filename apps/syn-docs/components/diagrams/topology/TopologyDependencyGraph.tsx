'use client';

// Source: APS VIZ01 substandard - https://github.com/AgentParadise/agent-paradise-standards-system
// This is a local copy of the VIZ01-dashboard TopologyDependencyGraph component.

import { useCallback, useMemo, useRef, useState } from 'react';
import type { DependencyEdge, ModuleMetric, TopoNode } from './shared/types';
import { buildTopologyGraph, type FilterOptions } from './shared/filters';
import { clamp, hitTest } from './shared/canvas-utils';
import { useForceSimulation } from './shared/useForceSimulation';
import { TopologyTooltip } from './TopologyTooltip';
import { TopologyLegend } from './TopologyLegend';

export interface TopologyDependencyGraphProps {
  dependencies: DependencyEdge[];
  modules: ModuleMetric[];
  height?: number;
  className?: string;
  filterOptions?: FilterOptions;
}

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
  const [tooltip, setTooltip] = useState<{ x: number; y: number; node: TopoNode } | null>(null);
  const dragRef = useRef({ active: false, lastX: 0, lastY: 0 });

  const { simNodesRef, transformRef, draw } = useForceSimulation(canvasRef, nodes, links);

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      transformRef.current.k = clamp(transformRef.current.k * (e.deltaY > 0 ? 0.9 : 1.1), 0.1, 8);
      draw();
    },
    [transformRef, draw],
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

      const hit = hitTest(sx, sy, canvas.width, canvas.height, transformRef.current, simNodesRef.current);
      setTooltip(hit ? { x: e.clientX, y: e.clientY, node: hit } : null);
    },
    [transformRef, simNodesRef, draw],
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
      <TopologyLegend />
      <TopologyTooltip tooltip={tooltip} />
    </div>
  );
}
