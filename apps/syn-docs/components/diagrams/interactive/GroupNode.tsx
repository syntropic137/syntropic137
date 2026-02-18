'use client';

import { memo } from 'react';
import type { NodeProps } from '@xyflow/react';
import { getColors } from './theme';
import { useThemeMode } from './useThemeMode';
import type { GroupNodeData } from './types';

function GroupNodeComponent({ data, width, height }: NodeProps) {
  const { title, color = 'slate' } = data as GroupNodeData;
  const isDark = useThemeMode();
  const colors = getColors(color, isDark);

  return (
    <div
      style={{
        width: width ?? 300,
        height: height ?? 200,
        borderRadius: 12,
        border: `1px dashed ${colors.groupBorder}`,
        background: colors.groupBg,
        backdropFilter: 'blur(4px)',
        padding: '12px 16px',
      }}
    >
      <span style={{
        fontSize: '10px',
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        color: colors.text,
      }}>
        {title}
      </span>
    </div>
  );
}

export const GroupNode = memo(GroupNodeComponent);
