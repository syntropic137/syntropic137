import type { Edge } from '@xyflow/react';
import type { AnimatedEdgeData, EdgeSpeed } from './types';

// Default node dimensions by size
export const NODE_WIDTH = { sm: 140, md: 170, lg: 200 };
export const NODE_HEIGHT = { sm: 42, md: 50, lg: 60 };
export const GROUP_PADDING = { top: 40, side: 16, bottom: 16 };
export const GAP = { x: 30, y: 20 };

/**
 * Position nodes in a centered horizontal row.
 * Returns a map of nodeId → { x, y }.
 */
export function layoutRow(
  nodeIds: string[],
  y: number,
  centerX: number,
  gap: number = GAP.x,
  nodeWidth: number = NODE_WIDTH.md,
): Record<string, { x: number; y: number }> {
  const totalWidth = nodeIds.length * nodeWidth + (nodeIds.length - 1) * gap;
  const startX = centerX - totalWidth / 2;
  const positions: Record<string, { x: number; y: number }> = {};
  nodeIds.forEach((id, i) => {
    positions[id] = { x: startX + i * (nodeWidth + gap), y };
  });
  return positions;
}

/**
 * Position nodes in a grid layout.
 * Returns a map of nodeId → { x, y }.
 */
export function layoutGrid(
  nodeIds: string[],
  startX: number,
  startY: number,
  cols: number,
  gapX: number = GAP.x,
  gapY: number = GAP.y,
  nodeWidth: number = NODE_WIDTH.md,
  nodeHeight: number = NODE_HEIGHT.md,
): Record<string, { x: number; y: number }> {
  const positions: Record<string, { x: number; y: number }> = {};
  nodeIds.forEach((id, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    positions[id] = {
      x: startX + col * (nodeWidth + gapX),
      y: startY + row * (nodeHeight + gapY),
    };
  });
  return positions;
}

/**
 * Create a vertical edge (top→bottom handles, default).
 */
export function edge(
  source: string,
  target: string,
  label?: string,
  speed: EdgeSpeed = 'normal',
): Edge<AnimatedEdgeData> {
  return {
    id: `${source}-${target}`,
    source,
    target,
    sourceHandle: 'bottom',
    targetHandle: 'top',
    type: 'animatedEdge',
    data: { label, speed },
  };
}

/**
 * Create a horizontal edge (right→left handles).
 * Use for nodes positioned side by side in the same row.
 */
export function hedge(
  source: string,
  target: string,
  label?: string,
  speed: EdgeSpeed = 'normal',
): Edge<AnimatedEdgeData> {
  return {
    id: `${source}-${target}`,
    source,
    target,
    sourceHandle: 'right',
    targetHandle: 'left',
    type: 'animatedEdge',
    data: { label, speed },
  };
}
