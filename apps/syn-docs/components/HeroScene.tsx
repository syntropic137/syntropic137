'use client';

import { useRef, useMemo, useEffect, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
// drei no longer needed in this file — native three.js primitives used directly
import * as THREE from 'three';
import { DARK_COLORS, LIGHT_COLORS, useTheme } from './hero/constants';
import { NetworkNodes } from './hero/NetworkNodes';

// ---------------------------------------------------------------------------
// Reduced-motion hook
// ---------------------------------------------------------------------------
function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReduced(mq.matches);
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);
  return reduced;
}

// ---------------------------------------------------------------------------
// Floating Particles — varied sizes, color variation, accent highlights
// ---------------------------------------------------------------------------
function FloatingParticles({ isDark, reducedMotion }: { isDark: boolean; reducedMotion: boolean }) {
  const ref = useRef<THREE.Points>(null);
  const theme = isDark ? DARK_COLORS : LIGHT_COLORS;

  const { positions, sizes, colors } = useMemo(() => {
    const count = 800;
    const pos = new Float32Array(count * 3);
    const sz = new Float32Array(count);
    const col = new Float32Array(count * 3);

    const primaryColor = new THREE.Color(theme.particle);
    const accentColor = new THREE.Color(theme.particleAccent);
    const dimColor = new THREE.Color(theme.particleDim);

    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 18;
      pos[i * 3 + 1] = (Math.random() - 0.5) * 18;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 18;

      // Vary sizes: mostly small, a few larger for depth
      const r = Math.random();
      if (r < 0.05) {
        sz[i] = 0.06 + Math.random() * 0.04; // bright accent — larger
      } else if (r < 0.3) {
        sz[i] = 0.025 + Math.random() * 0.015; // medium
      } else {
        sz[i] = 0.008 + Math.random() * 0.012; // small / distant
      }

      // Color variation
      let c: THREE.Color;
      if (r < 0.05) {
        c = accentColor;
      } else if (r < 0.4) {
        c = primaryColor;
      } else {
        c = dimColor.clone().lerp(primaryColor, Math.random() * 0.4);
      }
      col[i * 3] = c.r;
      col[i * 3 + 1] = c.g;
      col[i * 3 + 2] = c.b;
    }

    return { positions: pos, sizes: sz, colors: col };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDark]);

  useFrame((state) => {
    if (ref.current && !reducedMotion) {
      ref.current.rotation.y = state.clock.elapsedTime * 0.01;
      ref.current.rotation.x = state.clock.elapsedTime * 0.006;
    }
  });

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[colors, 3]} />
      </bufferGeometry>
      <pointsMaterial
        transparent
        vertexColors
        size={0.025}
        sizeAttenuation
        depthWrite={false}
        opacity={isDark ? 0.7 : 0.5}
        blending={isDark ? THREE.AdditiveBlending : THREE.NormalBlending}
      />
    </points>
  );
}

// ---------------------------------------------------------------------------
// Central Core — nested rotating geometry with emissive glow + breathing
// ---------------------------------------------------------------------------
function CentralCore({ isDark, reducedMotion }: { isDark: boolean; reducedMotion: boolean }) {
  const outerRef = useRef<THREE.Mesh>(null);
  const middleRef = useRef<THREE.Mesh>(null);
  const innerRef = useRef<THREE.Mesh>(null);
  const glowSphereRef = useRef<THREE.Mesh>(null);
  const pulseRef = useRef<THREE.Mesh>(null);
  const theme = isDark ? DARK_COLORS : LIGHT_COLORS;

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (reducedMotion) return;

    // Outer icosahedron — slow tumble
    if (outerRef.current) {
      outerRef.current.rotation.y = t * 0.15;
      outerRef.current.rotation.x = t * 0.1;
      const s = 1 + Math.sin(t * 0.8) * 0.03;
      outerRef.current.scale.set(s, s, s);
    }

    // Middle icosahedron — counter-rotate
    if (middleRef.current) {
      middleRef.current.rotation.y = -t * 0.35;
      middleRef.current.rotation.z = t * 0.2;
      const s = 1 + Math.sin(t * 1.2 + 1) * 0.04;
      middleRef.current.scale.set(s, s, s);
    }

    // Inner dodecahedron — faster spin
    if (innerRef.current) {
      innerRef.current.rotation.y = t * 0.6;
      innerRef.current.rotation.x = -t * 0.3;
      const s = 1 + Math.sin(t * 1.8 + 2) * 0.05;
      innerRef.current.scale.set(s, s, s);
    }

    // Glow sphere — breathing
    if (glowSphereRef.current) {
      const breath = 1 + Math.sin(t * 1.5) * 0.08;
      glowSphereRef.current.scale.set(breath, breath, breath);
      const mat = glowSphereRef.current.material as THREE.MeshBasicMaterial;
      mat.opacity = (isDark ? 0.15 : 0.1) + Math.sin(t * 1.5) * 0.05;
    }

    // Pulse ring — expanding ring effect
    if (pulseRef.current) {
      const cycle = (t * 0.4) % 1; // 0..1 repeating
      const s = 0.4 + cycle * 0.8;
      pulseRef.current.scale.set(s, s, s);
      const mat = pulseRef.current.material as THREE.MeshBasicMaterial;
      mat.opacity = (1 - cycle) * (isDark ? 0.15 : 0.1);
    }
  });

  return (
    <group>
      {/* Soft ambient glow sphere */}
      <mesh ref={glowSphereRef}>
        <sphereGeometry args={[0.9, 32, 32]} />
        <meshBasicMaterial
          color={theme.coreGlow}
          transparent
          opacity={isDark ? 0.12 : 0.08}
          depthWrite={false}
          blending={isDark ? THREE.AdditiveBlending : THREE.NormalBlending}
        />
      </mesh>

      {/* Expanding pulse ring */}
      <mesh ref={pulseRef} rotation={[Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.95, 1.0, 64]} />
        <meshBasicMaterial
          color={theme.coreGlow}
          transparent
          opacity={0.1}
          side={THREE.DoubleSide}
          depthWrite={false}
          blending={isDark ? THREE.AdditiveBlending : THREE.NormalBlending}
        />
      </mesh>

      {/* Outer wireframe — icosahedron detail=1 */}
      <mesh ref={outerRef}>
        <icosahedronGeometry args={[0.65, 1]} />
        <meshBasicMaterial
          color={theme.coreOuter}
          wireframe
          transparent
          opacity={isDark ? 0.18 : 0.3}
        />
      </mesh>

      {/* Middle wireframe — icosahedron detail=2 for denser mesh */}
      <mesh ref={middleRef}>
        <icosahedronGeometry args={[0.45, 2]} />
        <meshBasicMaterial
          color={theme.coreMiddle}
          wireframe
          transparent
          opacity={isDark ? 0.35 : 0.5}
        />
      </mesh>

      {/* Inner wireframe — dodecahedron for geometric contrast */}
      <mesh ref={innerRef}>
        <dodecahedronGeometry args={[0.28, 0]} />
        <meshBasicMaterial
          color={theme.coreInner}
          wireframe
          transparent
          opacity={0.7}
        />
      </mesh>

      {/* Solid emissive core */}
      <mesh>
        <sphereGeometry args={[0.14, 24, 24]} />
        <meshStandardMaterial
          color={theme.coreInner}
          emissive={theme.coreGlow}
          emissiveIntensity={isDark ? 2.0 : 0.8}
          transparent
          opacity={0.95}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}

// ---------------------------------------------------------------------------
// Segmented Orbital Rings — dashed arcs at different angles/speeds
// ---------------------------------------------------------------------------
function OrbitalRings({ isDark, reducedMotion }: { isDark: boolean; reducedMotion: boolean }) {
  const theme = isDark ? DARK_COLORS : LIGHT_COLORS;

  return (
    <group>
      <OrbitalRing
        radius={0.85}
        color={theme.ring1}
        opacity={isDark ? 0.5 : 0.6}
        rotation={[Math.PI / 2, 0, 0]}
        speed={0.3}
        segments={8}
        gapRatio={0.25}
        tubeRadius={0.008}
        isDark={isDark}
        reducedMotion={reducedMotion}
      />
      <OrbitalRing
        radius={1.1}
        color={theme.ring2}
        opacity={isDark ? 0.35 : 0.45}
        rotation={[Math.PI / 3, Math.PI / 6, 0]}
        speed={-0.2}
        segments={12}
        gapRatio={0.3}
        tubeRadius={0.006}
        isDark={isDark}
        reducedMotion={reducedMotion}
      />
      <OrbitalRing
        radius={1.35}
        color={theme.ring3}
        opacity={isDark ? 0.2 : 0.3}
        rotation={[Math.PI / 5, -Math.PI / 4, Math.PI / 8]}
        speed={0.15}
        segments={6}
        gapRatio={0.35}
        tubeRadius={0.005}
        isDark={isDark}
        reducedMotion={reducedMotion}
      />
      <OrbitalRing
        radius={1.6}
        color={theme.ring4}
        opacity={isDark ? 0.12 : 0.2}
        rotation={[-Math.PI / 4, Math.PI / 3, -Math.PI / 6]}
        speed={-0.1}
        segments={10}
        gapRatio={0.4}
        tubeRadius={0.004}
        isDark={isDark}
        reducedMotion={reducedMotion}
      />
    </group>
  );
}

// Proper orbital ring that positions arc segments around a circle
function OrbitalRing({
  radius,
  color,
  opacity,
  rotation,
  speed,
  segments,
  gapRatio,
  tubeRadius,
  isDark,
  reducedMotion,
}: {
  radius: number;
  color: string;
  opacity: number;
  rotation: [number, number, number];
  speed: number;
  segments: number;
  gapRatio: number;
  tubeRadius: number;
  isDark: boolean;
  reducedMotion: boolean;
}) {
  const groupRef = useRef<THREE.Group>(null);

  const arcData = useMemo(() => {
    const fullArc = (Math.PI * 2) / segments;
    const segArc = fullArc * (1 - gapRatio);
    return Array.from({ length: segments }, (_, i) => ({
      startAngle: i * fullArc,
      arc: segArc,
    }));
  }, [segments, gapRatio]);

  useFrame((state) => {
    if (groupRef.current && !reducedMotion) {
      groupRef.current.rotation.z += speed * 0.005;
    }
  });

  return (
    <group ref={groupRef} rotation={rotation}>
      {arcData.map((seg, i) => (
        <group key={i} rotation={[0, 0, seg.startAngle]}>
          <mesh>
            <torusGeometry args={[radius, tubeRadius, 6, Math.max(16, Math.round(seg.arc * 20)), seg.arc]} />
            <meshBasicMaterial
              color={color}
              transparent
              opacity={opacity * (0.7 + 0.3 * Math.sin((i / segments) * Math.PI))}
              depthWrite={false}
              blending={isDark ? THREE.AdditiveBlending : THREE.NormalBlending}
            />
          </mesh>
        </group>
      ))}
    </group>
  );
}

// ---------------------------------------------------------------------------
// Scene composition
// ---------------------------------------------------------------------------
function Scene({ isDark, reducedMotion }: { isDark: boolean; reducedMotion: boolean }) {
  return (
    <>
      {/* Soft ambient + directional for emissive materials */}
      <ambientLight intensity={isDark ? 0.1 : 0.3} />
      <pointLight position={[0, 0, 0]} intensity={isDark ? 0.5 : 0.3} color="#4d80ff" distance={8} decay={2} />
      <CentralCore isDark={isDark} reducedMotion={reducedMotion} />
      <OrbitalRings isDark={isDark} reducedMotion={reducedMotion} />
      <NetworkNodes isDark={isDark} reducedMotion={reducedMotion} />
      <FloatingParticles isDark={isDark} reducedMotion={reducedMotion} />
    </>
  );
}

export function HeroScene() {
  const isDark = useTheme();
  const reducedMotion = usePrefersReducedMotion();

  return (
    <div className="w-full h-full relative">
      <Canvas
        camera={{ position: [0, 0, 5.5], fov: 55 }}
        style={{ background: 'transparent' }}
        gl={{ alpha: true, antialias: true, powerPreference: 'high-performance' }}
        dpr={[1, 1.5]}
        aria-label="Interactive 3D visualization of the Syn137 architecture"
        role="img"
        tabIndex={-1}
      >
        <Scene isDark={isDark} reducedMotion={reducedMotion} />
      </Canvas>
    </div>
  );
}
