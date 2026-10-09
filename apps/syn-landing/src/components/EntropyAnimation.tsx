import { useEffect, useRef } from "react";

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  targetX: number;
  targetY: number;
}

export default function EntropyAnimation() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    let particles: Particle[] = [];
    let running = false;
    const gridSize = 40;
    const dotRadius = 1.2;

    // How long the settling takes (ms)
    const settleDuration = 6000;
    let startTime: number | null = null;
    let settledTime: number | null = null;

    const resize = () => {
      const rect = canvas.parentElement!.getBoundingClientRect();
      canvas.width = rect.width * devicePixelRatio;
      canvas.height = rect.height * devicePixelRatio;
      canvas.style.width = rect.width + "px";
      canvas.style.height = rect.height + "px";
      ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
      initParticles(rect.width, rect.height);
    };

    const initParticles = (w: number, h: number) => {
      particles = [];
      for (let gx = gridSize; gx < w; gx += gridSize) {
        for (let gy = gridSize; gy < h; gy += gridSize) {
          // Start scattered randomly
          particles.push({
            x: Math.random() * w,
            y: Math.random() * h,
            // Random initial velocities, like gas molecules
            vx: (Math.random() - 0.5) * 3,
            vy: (Math.random() - 0.5) * 3,
            targetX: gx,
            targetY: gy,
          });
        }
      }
    };

    const draw = (timestamp: number) => {
      if (!startTime) startTime = timestamp;
      const elapsed = timestamp - startTime;
      // 0 = full chaos, 1 = fully settled
      const progress = Math.min(elapsed / settleDuration, 1);

      const w = canvas.width / devicePixelRatio;
      const h = canvas.height / devicePixelRatio;
      ctx.clearRect(0, 0, w, h);

      // Chaos energy decreases over time
      const chaos = Math.pow(1 - progress, 2);
      // Attraction to grid increases over time
      const attraction = Math.pow(progress, 1.5) * 0.08;
      // Damping increases (slows particles down)
      const damping = 0.97 - progress * 0.04;

      // Draw grid lines that fade in as structure emerges
      if (progress > 0.4) {
        const lineAlpha = Math.pow((progress - 0.4) / 0.6, 2) * 0.07;
        ctx.strokeStyle = `rgba(77, 128, 255, ${lineAlpha})`;
        ctx.lineWidth = 0.5;
        for (let x = gridSize; x < w; x += gridSize) {
          ctx.beginPath();
          ctx.moveTo(x, 0);
          ctx.lineTo(x, h);
          ctx.stroke();
        }
        for (let y = gridSize; y < h; y += gridSize) {
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(w, y);
          ctx.stroke();
        }
      }

      // Update and draw particles
      for (const p of particles) {
        // Random Brownian jitter (entropy), decreasing over time
        p.vx += (Math.random() - 0.5) * chaos * 1.5;
        p.vy += (Math.random() - 0.5) * chaos * 1.5;

        // Spring attraction toward grid target
        const dx = p.targetX - p.x;
        const dy = p.targetY - p.y;
        p.vx += dx * attraction;
        p.vy += dy * attraction;

        // Damping (friction)
        p.vx *= damping;
        p.vy *= damping;

        // Update position
        p.x += p.vx;
        p.y += p.vy;

        // Particle appearance
        const dist = Math.sqrt(dx * dx + dy * dy);
        const settled = Math.max(0, 1 - dist / 80);
        const alpha = 0.12 + settled * 0.38;
        const radius = dotRadius + chaos * 1.2;

        // Color shifts from warm (entropy) to cool (structure)
        const r = Math.round(77 + chaos * 140);
        const g = Math.round(128 - chaos * 40);
        const b = Math.round(255 - chaos * 80);
        ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
        ctx.fill();
      }

      // After settling, add very subtle breathing drift then stop
      if (progress >= 1) {
        if (!settledTime) settledTime = timestamp;
        if (timestamp - settledTime > 3000) return; // stop loop, save CPU
        for (const p of particles) {
          p.vx += (Math.random() - 0.5) * 0.02;
          p.vy += (Math.random() - 0.5) * 0.02;
          const dx = p.targetX - p.x;
          const dy = p.targetY - p.y;
          p.vx += dx * 0.05;
          p.vy += dy * 0.05;
          p.vx *= 0.92;
          p.vy *= 0.92;
          p.x += p.vx;
          p.y += p.vy;
        }
      }

      animId = requestAnimationFrame(draw);
    };

    resize();

    // Start when footer scrolls into view
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !running) {
          running = true;
          startTime = null;
          animId = requestAnimationFrame(draw);
        }
      },
      { threshold: 0.1 }
    );
    observer.observe(canvas);

    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animId);
      observer.disconnect();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="entropy-canvas"
      aria-hidden="true"
    />
  );
}
