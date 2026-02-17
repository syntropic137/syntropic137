'use client';

import { useRef, useMemo, useEffect, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Points, PointMaterial } from '@react-three/drei';
import * as THREE from 'three';

// SR-71 palette: cold instrument blues, titanium grays
const DARK_COLORS = {
  agent: '#38BDF8',    // sky-400
  command: '#7DD3FC',  // sky-300
  skill: '#0EA5E9',   // sky-500
  tool: '#BAE6FD',    // sky-200
  hook: '#A1A1AA',    // zinc-400
  line: '#38BDF8',
  particle: '#7DD3FC',
  coreOuter: '#38BDF8',
  coreMiddle: '#0EA5E9',
  coreInner: '#7DD3FC',
  ring1: '#38BDF8',
  ring2: '#0EA5E9',
};

const LIGHT_COLORS = {
  agent: '#0284C7',    // sky-600
  command: '#0369A1',  // sky-700
  skill: '#0EA5E9',    // sky-500
  tool: '#38BDF8',     // sky-400
  hook: '#71717A',     // zinc-500
  line: '#0EA5E9',
  particle: '#0284C7',
  coreOuter: '#0EA5E9',
  coreMiddle: '#0284C7',
  coreInner: '#0369A1',
  ring1: '#0EA5E9',
  ring2: '#0284C7',
};

function useTheme() {
  const [isDark, setIsDark] = useState(true);

  useEffect(() => {
    const checkTheme = () => {
      setIsDark(document.documentElement.classList.contains('dark'));
    };

    checkTheme();

    const observer = new MutationObserver(checkTheme);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class'],
    });

    return () => observer.disconnect();
  }, []);

  return isDark;
}

function NetworkNodes({ isDark }: { isDark: boolean }) {
  const ref = useRef<THREE.Points>(null);
  const linesRef = useRef<THREE.LineSegments>(null);
  const lineMaterialRef = useRef<THREE.LineBasicMaterial>(null);
  const theme = isDark ? DARK_COLORS : LIGHT_COLORS;

  const [[positions, connections]] = useState(() => {
    const nodeCount = 80;
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

        if (dist < 1.2) {
          linePositions.push(
            pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2],
            pos[j * 3], pos[j * 3 + 1], pos[j * 3 + 2]
          );
        }
      }
    }

    return [pos, new Float32Array(linePositions)];
  });

  const colors = useMemo(() => {
    const nodeCount = 80;
    const cols = new Float32Array(nodeCount * 3);
    const colorKeys = [theme.agent, theme.command, theme.skill, theme.tool, theme.hook];

    for (let i = 0; i < nodeCount; i++) {
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

function FloatingParticles({ isDark }: { isDark: boolean }) {
  const ref = useRef<THREE.Points>(null);
  const theme = isDark ? DARK_COLORS : LIGHT_COLORS;

  const particles = useMemo(() => {
    const count = 300;
    const pos = new Float32Array(count * 3);

    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 12;
      pos[i * 3 + 1] = (Math.random() - 0.5) * 12;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 12;
    }

    return pos;
  }, []);

  useFrame((state) => {
    if (ref.current) {
      ref.current.rotation.y = state.clock.elapsedTime * 0.012;
      ref.current.rotation.x = state.clock.elapsedTime * 0.008;
    }
  });

  return (
    <Points ref={ref} positions={particles} stride={3}>
      <PointMaterial
        transparent
        color={theme.particle}
        size={0.02}
        sizeAttenuation={true}
        depthWrite={false}
        opacity={isDark ? 0.5 : 0.4}
        blending={isDark ? THREE.AdditiveBlending : THREE.NormalBlending}
      />
    </Points>
  );
}

function CentralCore({ isDark }: { isDark: boolean }) {
  const meshRef = useRef<THREE.Mesh>(null);
  const glowRef = useRef<THREE.Mesh>(null);
  const theme = isDark ? DARK_COLORS : LIGHT_COLORS;

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (meshRef.current) {
      meshRef.current.rotation.y = t * 0.4;
      meshRef.current.rotation.z = t * 0.25;
      const scale = 1 + Math.sin(t * 2) * 0.05;
      meshRef.current.scale.set(scale, scale, scale);
    }
    if (glowRef.current) {
      glowRef.current.rotation.y = -t * 0.25;
      glowRef.current.rotation.x = t * 0.15;
      const glowScale = 1.3 + Math.sin(t * 1.5) * 0.06;
      glowRef.current.scale.set(glowScale, glowScale, glowScale);
    }
  });

  return (
    <group>
      <mesh ref={glowRef}>
        <icosahedronGeometry args={[0.55, 1]} />
        <meshBasicMaterial
          color={theme.coreOuter}
          wireframe
          transparent
          opacity={isDark ? 0.2 : 0.35}
        />
      </mesh>

      <mesh ref={meshRef}>
        <icosahedronGeometry args={[0.38, 1]} />
        <meshBasicMaterial
          color={theme.coreMiddle}
          wireframe
          transparent
          opacity={0.8}
        />
      </mesh>

      <mesh>
        <sphereGeometry args={[0.18, 16, 16]} />
        <meshBasicMaterial color={theme.coreInner} transparent opacity={0.9} />
      </mesh>
    </group>
  );
}

function OrbitalRings({ isDark }: { isDark: boolean }) {
  const ring1Ref = useRef<THREE.Mesh>(null);
  const ring2Ref = useRef<THREE.Mesh>(null);
  const theme = isDark ? DARK_COLORS : LIGHT_COLORS;

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (ring1Ref.current) {
      ring1Ref.current.rotation.x = Math.PI / 2;
      ring1Ref.current.rotation.z = t * 0.35;
    }
    if (ring2Ref.current) {
      ring2Ref.current.rotation.y = Math.PI / 3;
      ring2Ref.current.rotation.z = -t * 0.25;
    }
  });

  return (
    <group>
      <mesh ref={ring1Ref}>
        <torusGeometry args={[0.85, 0.01, 16, 100]} />
        <meshBasicMaterial color={theme.ring1} transparent opacity={isDark ? 0.6 : 0.7} />
      </mesh>
      <mesh ref={ring2Ref}>
        <torusGeometry args={[1.05, 0.008, 16, 100]} />
        <meshBasicMaterial color={theme.ring2} transparent opacity={isDark ? 0.4 : 0.5} />
      </mesh>
    </group>
  );
}

function Scene({ isDark }: { isDark: boolean }) {
  return (
    <>
      <CentralCore isDark={isDark} />
      <OrbitalRings isDark={isDark} />
      <NetworkNodes isDark={isDark} />
      <FloatingParticles isDark={isDark} />
    </>
  );
}

export function HeroScene() {
  const isDark = useTheme();

  return (
    <div className="w-full h-[320px] md:h-[380px] relative -mt-4 mb-4">
      <Canvas
        camera={{ position: [0, 0, 5.5], fov: 55 }}
        style={{ background: 'transparent' }}
        gl={{ alpha: true, antialias: true }}
        aria-label="Interactive 3D visualization of the AEF architecture"
        role="img"
        tabIndex={-1}
      >
        <Scene isDark={isDark} />
      </Canvas>

      <div className="absolute inset-x-0 bottom-0 h-24 pointer-events-none bg-gradient-to-t from-fd-background to-transparent" />
    </div>
  );
}
