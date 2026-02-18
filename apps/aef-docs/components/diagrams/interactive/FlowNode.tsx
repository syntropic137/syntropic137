'use client';

import { memo, useState } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { LucideIcon } from 'lucide-react';
import {
  Terminal, Layout, Github, Server, Database, HardDrive,
  Workflow, Eye, Activity, Shield, Zap, GitBranch, Plug,
  Box, Layers, Radio, Send, Lock, Unlock, Play, Pause,
  Square, CheckCircle, XCircle, Globe, Container, Cpu, MonitorSmartphone,
} from 'lucide-react';
import { getColors } from './theme';
import { useThemeMode } from './useThemeMode';
import { NODE_WIDTH, NODE_HEIGHT } from './layout';
import type { FlowNodeData } from './types';

const iconMap: Record<string, LucideIcon> = {
  terminal: Terminal, layout: Layout, github: Github,
  server: Server, database: Database, drive: HardDrive,
  workflow: Workflow, eye: Eye, activity: Activity,
  shield: Shield, zap: Zap, git: GitBranch, plug: Plug,
  box: Box, layers: Layers, radio: Radio, send: Send,
  lock: Lock, unlock: Unlock, play: Play, pause: Pause,
  stop: Square, check: CheckCircle, x: XCircle,
  globe: Globe, container: Container, cpu: Cpu,
  monitor: MonitorSmartphone,
};

const iconSizes = { sm: 14, md: 16, lg: 20 };
const fontSizes = { sm: '11px', md: '12px', lg: '14px' };
const sublabelSizes = { sm: '9px', md: '10px', lg: '11px' };

// Completely invisible handle style
const hiddenHandle: React.CSSProperties = {
  width: 0,
  height: 0,
  minWidth: 0,
  minHeight: 0,
  border: 'none',
  background: 'transparent',
  opacity: 0,
  pointerEvents: 'none',
};

function FlowNodeComponent({ data }: NodeProps) {
  const { icon, label, sublabel, color = 'indigo', size = 'md' } = data as FlowNodeData;
  const isDark = useThemeMode();
  const colors = getColors(color, isDark);
  const [hovered, setHovered] = useState(false);

  const Icon = iconMap[icon] ?? Box;
  const w = NODE_WIDTH[size];
  const h = NODE_HEIGHT[size];

  return (
    <>
      <Handle type="target" id="top" position={Position.Top} style={hiddenHandle} />
      <Handle type="target" id="left" position={Position.Left} style={hiddenHandle} />
      <div
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          width: w,
          height: h,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: size === 'sm' ? 6 : 8,
          borderRadius: 8,
          border: `1px solid ${colors.border}`,
          background: hovered ? colors.bgHover : colors.bg,
          backdropFilter: 'blur(8px)',
          boxShadow: hovered ? `0 0 16px ${colors.glow}` : 'none',
          transition: 'background 0.2s, box-shadow 0.2s',
          cursor: 'default',
          padding: '0 12px',
        }}
      >
        <Icon
          size={iconSizes[size]}
          color={colors.icon}
          style={{ flexShrink: 0 }}
        />
        <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <span style={{
            fontSize: fontSizes[size],
            fontWeight: 500,
            color: colors.text,
            whiteSpace: 'nowrap',
            lineHeight: 1.3,
          }}>
            {label}
          </span>
          {sublabel && (
            <span style={{
              fontSize: sublabelSizes[size],
              color: isDark ? '#a1a1aa' : '#71717a',
              whiteSpace: 'nowrap',
              lineHeight: 1.2,
            }}>
              {sublabel}
            </span>
          )}
        </div>
      </div>
      <Handle type="source" id="bottom" position={Position.Bottom} style={hiddenHandle} />
      <Handle type="source" id="right" position={Position.Right} style={hiddenHandle} />
    </>
  );
}

export const FlowNode = memo(FlowNodeComponent);
