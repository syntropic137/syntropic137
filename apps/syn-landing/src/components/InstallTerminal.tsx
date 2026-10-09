import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { HERO, INSTALL_COMMAND } from "../data/copy";
import "./InstallTerminal.css";

interface InstallTerminalProps {
  className?: string;
  style?: CSSProperties;
  /** Type the command out once it is on screen (hero). The caret blinks only while visible, for about 20s. */
  typing?: boolean;
}

/**
 * The install box of the v4 boards: prompt, `npx @syntropic137/setup init`
 * and a Copy button. The full command is always in the DOM (and is the
 * static end state); typing only reveals it with motion.css sky-type.
 */
export default function InstallTerminal({ className, style, typing = false }: InstallTerminalProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [started, setStarted] = useState(false);
  const [visible, setVisible] = useState(false);
  const [copied, setCopied] = useState(false);

  // Start before first paint when already on screen, so the full command never flashes first.
  useLayoutEffect(() => {
    if (!typing || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    if (r.bottom > 0 && r.top < window.innerHeight) {
      setStarted(true);
      setVisible(true);
    }
  }, [typing]);

  useEffect(() => {
    const el = ref.current;
    if (!typing || !el || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver(([e]) => {
      if (!e) return;
      setVisible(e.isIntersecting);
      if (e.isIntersecting) setStarted(true);
    });
    io.observe(el);
    return () => io.disconnect();
  }, [typing]);

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(id);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(INSTALL_COMMAND);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  const chars = INSTALL_COMMAND.length;
  const typeStyle = { width: `${chars}ch`, animationTimingFunction: `steps(${chars})` } as CSSProperties;

  return (
    <div
      ref={ref}
      className={`install-box${className ? ` ${className}` : ""}`}
      style={style}
      data-paused={typing && !visible ? "" : undefined}
    >
      <span className="install-box__prompt" aria-hidden="true">
        ❯
      </span>
      <code className="install-box__code">
        <span className={typing && started ? "install-box__cmd sky-type" : "install-box__cmd"} style={typing ? typeStyle : undefined}>
          {INSTALL_COMMAND}
        </span>
        {typing && <span className={started ? "install-box__caret sky-blink" : "install-box__caret"} aria-hidden="true" />}
      </code>
      <button type="button" className="install-box__copy" onClick={copy} aria-label={HERO.copyAria}>
        <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          {copied ? (
            <path d="M3.5 8.5l3 3 6-7" />
          ) : (
            <>
              <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
              <path d="M10.5 5.5V3.5a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2" />
            </>
          )}
        </svg>
        <span aria-live="polite">{copied ? HERO.copiedLabel : HERO.copyLabel}</span>
      </button>
    </div>
  );
}
