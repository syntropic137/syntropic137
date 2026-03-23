import type { SimulationNodeDatum, SimulationLinkDatum } from 'd3-force';
import type { TopoNode } from './types';

export interface SimNode extends SimulationNodeDatum, TopoNode {}
export interface SimLink extends SimulationLinkDatum<SimNode> {
  weight: number;
}

export function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v));
}

export function nodeRadius(loc: number): number {
  return clamp(Math.sqrt(loc) * 0.35, 4, 28);
}

export function screenToWorld(
  sx: number,
  sy: number,
  canvasWidth: number,
  canvasHeight: number,
  transform: { x: number; y: number; k: number },
) {
  return {
    wx: (sx - transform.x - canvasWidth / 2) / transform.k,
    wy: (sy - transform.y - canvasHeight / 2) / transform.k,
  };
}

export function hitTest(
  sx: number,
  sy: number,
  canvasWidth: number,
  canvasHeight: number,
  transform: { x: number; y: number; k: number },
  simNodes: SimNode[],
): SimNode | null {
  const { wx, wy } = screenToWorld(sx, sy, canvasWidth, canvasHeight, transform);
  for (const n of simNodes) {
    if (n.x == null) continue;
    const r = nodeRadius(n.loc);
    const dx = n.x - wx;
    const dy = n.y! - wy;
    if (dx * dx + dy * dy <= r * r) return n;
  }
  return null;
}

export function drawGraph(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  transform: { x: number; y: number; k: number },
  simLinks: SimLink[],
  simNodes: SimNode[],
) {
  ctx.clearRect(0, 0, width, height);
  ctx.save();
  ctx.translate(transform.x + width / 2, transform.y + height / 2);
  ctx.scale(transform.k, transform.k);

  for (const l of simLinks) {
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

  for (const n of simNodes) {
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
}
