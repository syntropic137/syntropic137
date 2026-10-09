import { type CSSProperties, type ReactNode } from "react";

interface TextShimmerProps {
  children: ReactNode;
  /** Width of the shimmer beam in pixels */
  shimmerWidth?: number;
  className?: string;
}

export default function TextShimmer({
  children,
  shimmerWidth = 120,
  className = "",
}: TextShimmerProps) {
  return (
    <span
      className={`text-shimmer ${className}`}
      style={{ "--shimmer-width": `${shimmerWidth}px` } as CSSProperties}
    >
      {children}
    </span>
  );
}
