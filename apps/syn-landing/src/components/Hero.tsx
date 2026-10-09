import { useCallback, useEffect, useRef, useState } from "react";
import TextShimmer from "./TextShimmer";
import InstallTerminal from "./InstallTerminal";
import { ArrowRight, BookOpen, Scale } from "lucide-react";
import { HARNESSES } from "../data/harnesses";

const GitHubIcon = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
  </svg>
);

function useStaggerReveal(count: number, baseDelay = 0, stagger = 150) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.1 }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const getDelay = (index: number) => baseDelay + index * stagger;
  const getStyle = (index: number): React.CSSProperties => ({
    opacity: visible ? 1 : 0,
    transform: visible ? "translateY(0)" : "translateY(24px)",
    transition: `opacity 0.7s cubic-bezier(0.16, 1, 0.3, 1) ${getDelay(index)}ms, transform 0.7s cubic-bezier(0.16, 1, 0.3, 1) ${getDelay(index)}ms`,
  });

  return { ref, getStyle, visible };
}

function TypingText({ text, delay = 0 }: { text: string; delay?: number }) {
  const [displayed, setDisplayed] = useState("");
  const [started, setStarted] = useState(false);

  useEffect(() => {
    const timeout = setTimeout(() => setStarted(true), delay);
    return () => clearTimeout(timeout);
  }, [delay]);

  useEffect(() => {
    if (!started) return;
    let i = 0;
    const interval = setInterval(() => {
      i++;
      setDisplayed(text.slice(0, i));
      if (i >= text.length) clearInterval(interval);
    }, 40);
    return () => clearInterval(interval);
  }, [started, text]);

  return (
    <span className="typing-text">
      {displayed}
      <span className="typing-cursor" aria-hidden="true">|</span>
    </span>
  );
}

function useVideoToStill() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [posterSrc, setPosterSrc] = useState<string | null>(null);

  const handleEnded = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
      if (blob) setPosterSrc(URL.createObjectURL(blob));
    }, "image/webp");
  }, []);

  return { videoRef, posterSrc, handleEnded };
}

export default function Hero() {
  const hero = useStaggerReveal(7, 100, 150);
  const defs = useStaggerReveal(3, 200, 200);
  const { videoRef, posterSrc, handleEnded } = useVideoToStill();

  return (
    <section className="hero-section" ref={hero.ref}>
      {/* Ambient glow orbs */}
      <div className="hero-glow hero-glow--primary" aria-hidden="true" />
      <div className="hero-glow hero-glow--secondary" aria-hidden="true" />

      <div className="container hero">
        <div className="hero-text">
          <div style={hero.getStyle(0)}>
            <span className="hero-eyebrow">
              <Scale size={12} />
              <span>MIT</span>
              <span className="eyebrow-sep" aria-hidden="true" />
              <span>Agentic Engineering Platform</span>
            </span>
          </div>

          <h1 style={hero.getStyle(1)}>
            IDEs are <span className="accent">dead.</span>
          </h1>

          <p className="hero-subtitle" style={hero.getStyle(2)}>
            Get out of the loop.{" "}
            <TextShimmer shimmerWidth={140}>
              Get into orchestration.
            </TextShimmer>
          </p>

          <p className="hero-description" style={hero.getStyle(2)}>
            Running 10 coding agents in a terminal is about as far as you can
            go. <span className="syntropic-brand">Syntropic137</span> is{" "}
            <strong>multi-harness orchestration</strong>: run{" "}
            {HARNESSES.map((h, i) => (
              <span key={h.id}>
                {i > 0 && (i === HARNESSES.length - 1 ? " and " : ", ")}
                <span className={`harness ${h.accentClass}`}>{h.name}</span>
              </span>
            ))}{" "}
            across workflows, with every tool call and conversation captured.
          </p>

          <InstallTerminal className="hero-install" style={hero.getStyle(3)} />

          <div className="hero-ctas" style={hero.getStyle(4)}>
            <a
              href="https://github.com/syntropic137/syntropic137"
              className="btn-primary"
              target="_blank"
              rel="noopener noreferrer"
            >
              <GitHubIcon size={16} />
              <span>View on GitHub</span>
            </a>
            <a href="https://docs.syntropic137.com" className="btn-ghost" target="_blank" rel="noopener noreferrer">
              <BookOpen size={16} strokeWidth={2} />
              <span>Docs</span>
            </a>
          </div>
        </div>

        <div className="hero-visual" style={hero.getStyle(2)}>
          <div className="hero-visual-glow">
            <div className="hero-visual-frame">
              {posterSrc ? (
                <img
                  className="hero-video"
                  src={posterSrc}
                  alt="Syntropic137 logo"
                />
              ) : (
                <video
                  ref={videoRef}
                  className="hero-video"
                  autoPlay
                  muted
                  playsInline
                  aria-label="Syntropic137 logo"
                  src="/assets/hero_syntropic137.webm"
                  onEnded={handleEnded}
                />
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="container hero-definitions" ref={defs.ref}>
        <div className="syntropic-pair">
          <div className="syntropic-block" style={defs.getStyle(0)}>
            <p className="syntropic-label">Syntropic</p>
            <p className="syntropic-one-liner">Structure from entropy.</p>
            <p className="syntropic-note">
              From <em>syntropy</em>, the tendency toward order and
              complexity along energy gradients.
            </p>
          </div>
          <div className="syntropic-divider" style={defs.getStyle(1)} />
          <div className="syntropic-block" style={defs.getStyle(2)}>
            <p className="syntropic-label">137</p>
            <p className="syntropic-one-liner">The constant that makes it possible.</p>
            <p className="syntropic-note">
              The fine-structure constant (~1/137). Governs how matter
              and light interact.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
