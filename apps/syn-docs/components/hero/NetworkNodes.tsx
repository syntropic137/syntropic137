'use client';

import { useRef, useMemo, useEffect, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import { Points, PointMaterial } from '@react-three/drei';
import * as THREE from 'three';
import { DARK_COLORS, LIGHT_COLORS } from './constants';

const NODE_COUNT = 80;
const CONNECTION_THRESHOLD = 1.2;

function createNetworkGeometry(nodeCount: number, threshold: number) {
  const pos = new Float32Array(nodeCount * 3);

  for (let i = 0; i < nodeCount; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const r = 1.8 + Math.random() * 1.8;

    pos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    pos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    pos[i * 3 + 2] = r * Math.cos(phi);
  }

  const linePositions: number[] = [];
  for (let i = 0; i < nodeCount; i++) {
    for (let j = i + 1; j < nodeCount; j++) {
      const dx = pos[i * 3] - pos[j * 3];
      const dy = pos[i * 3 + 1] - pos[j * 3 + 1];
      const dz = pos[i * 3 + 2] - pos[j * 3 + 2];
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);

      if (dist < threshold) {
        linePositions.push(
          pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2],
          pos[j * 3], pos[j * 3 + 1], pos[j * 3 + 2]
        );
      }
    }
  }

  return [pos, new Float32Array(linePositions)] as const;
}

export function NetworkNodes({ isDark }: { isDark: boolean }) {
  const ref = useRef<THREE.Points>(null);
  const linesRef = useRef<THREE.LineSegments>(null);
  const lineMaterialRef = useRef<THREE.LineBasicMaterial>(null);
  const theme = isDark ? DARK_COLORS : LIGHT_COLORS;

  const [[positions, connections]] = useState(() => createNetworkGeometry(NODE_COUNT, CONNECTION_THRESHOLD));

  const colors = useMemo(() => {
    const cols = new Float32Array(NODE_COUNT * 3);
    const colorKeys = [theme.agent, theme.command, theme.skill, theme.tool, theme.hook];

    for (let i = 0; i < NODE_COUNT; i++) {
      const color = new THREE.Color(colorKeys[Math.floor(Math.random() * colorKeys.length)]);
      cols[i * 3] = color.r;
      cols[i * 3 + 1] = color.g;
      cols[i * 3 + 2] = color.b;
    }
    return cols;
  }, [theme]);

  useEffect(() => {
    if (lineMaterialRef.current) {
      lineMaterialRef.current.color.set(theme.line);
    }
  }, [theme]);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (ref.current) {
      ref.current.rotation.y = t * 0.06;
      ref.current.rotation.x = Math.sin(t * 0.04) * 0.1;
    }
    if (linesRef.current) {
      linesRef.current.rotation.y = t * 0.06;
      linesRef.current.rotation.x = Math.sin(t * 0.04) * 0.1;
    }
  });

  return (
    <group>
      <lineSegments ref={linesRef}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[connections, 3]}
          />
        </bufferGeometry>
        <lineBasicMaterial ref={lineMaterialRef} color={theme.line} transparent opacity={isDark ? 0.25 : 0.4} />
      </lineSegments>

      <Points ref={ref} positions={positions} stride={3}>
        <PointMaterial
          transparent
          vertexColors
          size={0.12}
          sizeAttenuation={true}
          depthWrite={false}
          blending={isDark ? THREE.AdditiveBlending : THREE.NormalBlending}
        />
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            args={[positions, 3]}
          />
          <bufferAttribute
            attach="attributes-color"
            args={[colors, 3]}
          />
        </bufferGeometry>
      </Points>
    </group>
  );
}
