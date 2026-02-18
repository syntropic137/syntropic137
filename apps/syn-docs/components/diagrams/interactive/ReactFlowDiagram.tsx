'use client';

import { useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import './flow.css';
import { FlowNode } from './FlowNode';
import { GroupNode } from './GroupNode';
import { AnimatedEdge } from './AnimatedEdge';
import { useThemeMode } from './useThemeMode';
import { getDotColor } from './theme';

const nodeTypes: NodeTypes = {
  flowNode: FlowNode,
  groupNode: GroupNode,
};

const edgeTypes: EdgeTypes = {
  animatedEdge: AnimatedEdge,
};

interface ReactFlowDiagramProps {
  nodes: Node[];
  edges: Edge[];
  minHeight?: number;
}

// Ensure group nodes render behind flow nodes and edges
function applyZIndex(nodes: Node[]): Node[] {
  return nodes.map(node => {
    if (node.type === 'groupNode') {
      return { ...node, style: { ...node.style, zIndex: -1 } };
    }
    return { ...node, style: { ...node.style, zIndex: 1 } };
  });
}

export function ReactFlowDiagram({ nodes, edges, minHeight = 400 }: ReactFlowDiagramProps) {
  const isDark = useThemeMode();
  const layeredNodes = useMemo(() => applyZIndex(nodes), [nodes]);

  return (
    <div
      style={{ width: '100%', height: minHeight, overflow: 'hidden' }}
      className="my-6 rounded-xl border border-fd-border bg-fd-card/50"
    >
      <ReactFlow
        nodes={layeredNodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
        minZoom={0.3}
        maxZoom={2}
      >
        <Background
          color={getDotColor(isDark)}
          gap={20}
          size={1}
        />
        <Controls
          showInteractive={false}
          position="bottom-right"
        />
      </ReactFlow>
    </div>
  );
}
