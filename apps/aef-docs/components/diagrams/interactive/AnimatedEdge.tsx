'use client';

import { memo } from 'react';
import {
  EdgeLabelRenderer,
  type EdgeProps,
  getSmoothStepPath,
} from '@xyflow/react';
import { getEdgeColor, getEdgeLabelColor } from './theme';
import { useThemeMode } from './useThemeMode';
import type { AnimatedEdgeData } from './types';

const speedDurations = { slow: '3s', normal: '1.5s', fast: '0.8s' };

function AnimatedEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  style,
}: EdgeProps) {
  const isDark = useThemeMode();
  const edgeColor = getEdgeColor(isDark);
  const labelColor = getEdgeLabelColor(isDark);
  const speed = (data as AnimatedEdgeData)?.speed ?? 'normal';
  const label = (data as AnimatedEdgeData)?.label;

  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 8,
  });

  return (
    <>
      {/* Background path */}
      <path
        d={edgePath}
        fill="none"
        stroke={edgeColor}
        strokeWidth={1.5}
        style={style}
      />
      {/* Animated dash overlay */}
      <path
        d={edgePath}
        fill="none"
        stroke={edgeColor}
        strokeWidth={1.5}
        strokeDasharray="6 4"
        style={{
          animation: `flowDash ${speedDurations[speed]} linear infinite`,
          ...style,
        }}
      />
      {/* Arrowhead */}
      <circle
        cx={targetX}
        cy={targetY}
        r={3}
        fill={edgeColor}
      />
      {/* Label */}
      {label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              fontSize: '10px',
              fontWeight: 500,
              color: labelColor,
              background: isDark ? 'rgba(39, 39, 42, 0.9)' : 'rgba(244, 244, 245, 0.9)',
              padding: '2px 6px',
              borderRadius: 4,
              whiteSpace: 'nowrap',
              pointerEvents: 'none',
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const AnimatedEdge = memo(AnimatedEdgeComponent);
