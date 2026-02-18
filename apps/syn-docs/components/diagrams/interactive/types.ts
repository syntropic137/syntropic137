import type { Node, Edge } from '@xyflow/react';

export type ColorVariant = 'indigo' | 'purple' | 'pink' | 'cyan' | 'slate' | 'emerald' | 'amber';
export type NodeSize = 'sm' | 'md' | 'lg';
export type EdgeSpeed = 'slow' | 'normal' | 'fast';

export interface FlowNodeData {
  icon: string;
  label: string;
  sublabel?: string;
  color: ColorVariant;
  size?: NodeSize;
  [key: string]: unknown;
}

export interface GroupNodeData {
  title: string;
  color: ColorVariant;
  [key: string]: unknown;
}

export interface AnimatedEdgeData {
  label?: string;
  speed?: EdgeSpeed;
  [key: string]: unknown;
}

export type FlowNode = Node<FlowNodeData, 'flowNode'>;
export type GroupNode = Node<GroupNodeData, 'groupNode'>;
export type AnimatedEdge = Edge<AnimatedEdgeData>;
