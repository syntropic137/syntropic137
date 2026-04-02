'use client';

/// <reference types="@react-three/fiber" />
import { useRef, useMemo, useEffect, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
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
const PARTICLE_COUNT = 800;
const PARTICLE_SPREAD = 18;

function generateParticleData(theme: typeof DARK_COLORS) {
  const pos = new Float32Array(PARTICLE_COUNT * 3);
  const sz = new Float32Array(PARTICLE_COUNT);
  const col = new Float32Array(PARTICLE_COUNT * 3);

  const primaryColor = new THREE.Color(theme.particle);
  const accentColor = new THREE.Color(theme.particleAccent);
  const dimColor = new THREE.Color(theme.particleDim);

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    pos[i * 3] = (Math.random() - 0.5) * PARTICLE_SPREAD;
    pos[i * 3 + 1] = (Math.random() - 0.5) * PARTICLE_SPREAD;
    pos[i * 3 + 2] = (Math.random() - 0.5) * PARTICLE_SPREAD;

    const r = Math.random();
    sz[i] = r < 0.05 ? 0.06 + Math.random() * 0.04
          : r < 0.3  ? 0.025 + Math.random() * 0.015
          :            0.008 + Math.random() * 0.012;

    const c = r < 0.05 ? accentColor
            : r < 0.4  ? primaryColor
            :            dimColor.clone().lerp(primaryColor, Math.random() * 0.4);
    col[i * 3] = c.r;
    col[i * 3 + 1] = c.g;
    col[i * 3 + 2] = c.b;
  }

  return { positions: pos, sizes: sz, colors: col };
}

function FloatingParticles({ isDark, reducedMotion }: { isDark: boolean; reducedMotion: boolean }) {
  const ref = useRef<THREE.Points>(null);
  const theme = isDark ? DARK_COLORS : LIGHT_COLORS;

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const { positions, sizes, colors } = useMemo(() => generateParticleData(theme), [isDark]);

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
function animateMesh(mesh: THREE.Mesh | null, t: number, rotY: number, rotX: number, rotZ: number, breathSpeed: number, breathAmp: number, offset: number) {
  if (!mesh) return;
  mesh.rotation.y = t * rotY;
  mesh.rotation.x = t * rotX;
  if (rotZ) mesh.rotation.z = t * rotZ;
  const s = 1 + Math.sin(t * breathSpeed + offset) * breathAmp;
  mesh.scale.set(s, s, s);
}

function CoreGlow({ isDark, glowRef, pulseRef, color }: {
  isDark: boolean; glowRef: React.RefObject<THREE.Mesh | null>; pulseRef: React.RefObject<THREE.Mesh | null>; color: string;
}) {
  const blending = isDark ? THREE.AdditiveBlending : THREE.NormalBlending;
  return (
    <>
      <mesh ref={glowRef}>
        <sphereGeometry args={[0.9, 32, 32]} />
        <meshBasicMaterial color={color} transparent opacity={isDark ? 0.12 : 0.08} depthWrite={false} blending={blending} />
      </mesh>
      <mesh ref={pulseRef} rotation={[Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.95, 1.0, 64]} />
        <meshBasicMaterial color={color} transparent opacity={0.1} side={THREE.DoubleSide} depthWrite={false} blending={blending} />
      </mesh>
    </>
  );
}

function CoreGeometry({ isDark, outerRef, middleRef, innerRef, theme }: {
  isDark: boolean; outerRef: React.RefObject<THREE.Mesh | null>; middleRef: React.RefObject<THREE.Mesh | null>; innerRef: React.RefObject<THREE.Mesh | null>; theme: typeof DARK_COLORS;
}) {
  return (
    <>
      <mesh ref={outerRef}>
        <icosahedronGeometry args={[0.65, 1]} />
        <meshBasicMaterial color={theme.coreOuter} wireframe transparent opacity={isDark ? 0.18 : 0.3} />
      </mesh>
      <mesh ref={middleRef}>
        <icosahedronGeometry args={[0.45, 2]} />
        <meshBasicMaterial color={theme.coreMiddle} wireframe transparent opacity={isDark ? 0.35 : 0.5} />
      </mesh>
      <mesh ref={innerRef}>
        <dodecahedronGeometry args={[0.28, 0]} />
        <meshBasicMaterial color={theme.coreInner} wireframe transparent opacity={0.7} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.14, 24, 24]} />
        <meshStandardMaterial color={theme.coreInner} emissive={theme.coreGlow} emissiveIntensity={isDark ? 2.0 : 0.8} transparent opacity={0.95} toneMapped={false} />
      </mesh>
    </>
  );
}

function animateGlow(mesh: THREE.Mesh, t: number, baseOpacity: number) {
  const breath = 1 + Math.sin(t * 1.5) * 0.08;
  mesh.scale.set(breath, breath, breath);
  (mesh.material as THREE.MeshBasicMaterial).opacity = baseOpacity + Math.sin(t * 1.5) * 0.05;
}

function animatePulse(mesh: THREE.Mesh, t: number, baseOpacity: number) {
  const cycle = (t * 0.4) % 1;
  const s = 0.4 + cycle * 0.8;
  mesh.scale.set(s, s, s);
  (mesh.material as THREE.MeshBasicMaterial).opacity = (1 - cycle) * baseOpacity;
}

function useCoreAnimation(isDark: boolean, reducedMotion: boolean, refs: {
  outer: React.RefObject<THREE.Mesh | null>; middle: React.RefObject<THREE.Mesh | null>; inner: React.RefObject<THREE.Mesh | null>;
  glow: React.RefObject<THREE.Mesh | null>; pulse: React.RefObject<THREE.Mesh | null>;
}) {
  const glowBase = isDark ? 0.15 : 0.1;
  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (reducedMotion) return;
    animateMesh(refs.outer.current, t, 0.15, 0.1, 0, 0.8, 0.03, 0);
    animateMesh(refs.middle.current, t, -0.35, 0, 0.2, 1.2, 0.04, 1);
    animateMesh(refs.inner.current, t, 0.6, -0.3, 0, 1.8, 0.05, 2);
    if (refs.glow.current) animateGlow(refs.glow.current, t, glowBase);
    if (refs.pulse.current) animatePulse(refs.pulse.current, t, glowBase);
  });
}

function CentralCore({ isDark, reducedMotion }: { isDark: boolean; reducedMotion: boolean }) {
  const outerRef = useRef<THREE.Mesh>(null);
  const middleRef = useRef<THREE.Mesh>(null);
  const innerRef = useRef<THREE.Mesh>(null);
  const glowRef = useRef<THREE.Mesh>(null);
  const pulseRef = useRef<THREE.Mesh>(null);
  const theme = isDark ? DARK_COLORS : LIGHT_COLORS;

  useCoreAnimation(isDark, reducedMotion, { outer: outerRef, middle: middleRef, inner: innerRef, glow: glowRef, pulse: pulseRef });

  return (
    <group>
      <CoreGlow isDark={isDark} glowRef={glowRef} pulseRef={pulseRef} color={theme.coreGlow} />
      <CoreGeometry isDark={isDark} outerRef={outerRef} middleRef={middleRef} innerRef={innerRef} theme={theme} />
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
