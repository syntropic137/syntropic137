import { useCallback, useEffect, useRef } from 'react';
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
} from 'd3-force';
import type { TopoNode, TopoLink } from './types';
import { clamp, nodeRadius, drawGraph, type SimNode, type SimLink } from './canvas-utils';

export function useForceSimulation(
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  nodes: TopoNode[],
  links: TopoLink[],
) {
  const simNodesRef = useRef<SimNode[]>([]);
  const simLinksRef = useRef<SimLink[]>([]);
  const transformRef = useRef({ x: 0, y: 0, k: 1 });

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    drawGraph(ctx, canvas.width, canvas.height, transformRef.current, simLinksRef.current, simNodesRef.current);
  }, [canvasRef]);

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
  }, [canvasRef, nodes, links, draw]);

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
  }, [canvasRef, draw]);

  return { simNodesRef, transformRef, draw };
}
