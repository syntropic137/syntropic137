import type { CSSProperties, ReactNode } from "react";
import "./GlassCard.css";

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  /** Finite bob from motion.css (3 cycles): "bob" (7s) or "alt" (8s, offset, reversed). None by default. */
  float?: "bob" | "alt";
  /** Extra start delay for the bob, in seconds. */
  delay?: number;
  style?: CSSProperties;
}

/**
 * Frosted card that floats over the hero city (v4 boards): glass surface,
 * blur and a soft drop shadow. The bob runs a few cycles and stops; with
 * reduced motion the card stays still.
 */
export default function GlassCard({ children, className, float, delay, style }: GlassCardProps) {
  return (
    <div
      className={`glass-card${float ? " sky-bob" : ""}${className ? ` ${className}` : ""}`}
      data-motion={float === "alt" ? "alt" : undefined}
      style={delay ? { ...style, animationDelay: `${delay}s` } : style}
    >
      {children}
    </div>
  );
}
