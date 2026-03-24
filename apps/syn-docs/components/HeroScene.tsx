'use client';

import { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Points, PointMaterial } from '@react-three/drei';
import * as THREE from 'three';
import { DARK_COLORS, LIGHT_COLORS, useTheme } from './hero/constants';
import { NetworkNodes } from './hero/NetworkNodes';

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
        aria-label="Interactive 3D visualization of the Syn137 architecture"
        role="img"
        tabIndex={-1}
      >
        <Scene isDark={isDark} />
      </Canvas>

      <div className="absolute inset-x-0 bottom-0 h-24 pointer-events-none bg-gradient-to-t from-fd-background to-transparent" />
    </div>
  );
}
